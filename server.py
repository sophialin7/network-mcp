import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
import random
import time
import sys

import firebase_admin
from firebase_admin import credentials, firestore
import anthropic

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from datetime import datetime, timezone

from google.cloud.firestore_v1.base_query import FieldFilter

# Initialize Firebase with error handling
db = None
try:
    cred = credentials.Certificate('firebase.json')
    firebase_app = firebase_admin.initialize_app(cred)
    db = firestore.client()
    client = anthropic.Anthropic(api_key="redacted")

    print("Firebase initialized successfully", file=sys.stderr, flush=True)
except Exception as e:
    print(f"Warning: Firebase initialization failed: {e}", file=sys.stderr, flush=True)
    print("Server will continue with in-memory storage only", file=sys.stderr, flush=True)

# Initialize MCP server
app = Server("home-network-copilot")

# Fallback devices if Firestore is empty
DEFAULT_DEVICES = {
    "router": {"type": "gateway", "location": "office", "status": "online"},
    "living_room_tv": {"type": "streaming", "location": "living_room", "status": "online"},
    "office_pc": {"type": "workstation", "location": "office", "status": "online"}
}

def get_devices_from_db():
    """Get devices from Firestore or return defaults"""
    if db is None:
        return DEFAULT_DEVICES
    
    try:
        devices_ref = db.collection("devices").stream()
        devices = {doc.id: doc.to_dict() for doc in devices_ref}
        return devices if devices else DEFAULT_DEVICES
    except Exception as e:
        print(f"Error fetching devices: {e}", file=sys.stderr, flush=True)
        return DEFAULT_DEVICES

def log_network_status(status_data):
    """Log network status to Firestore"""
    if db is None:
        print("Skipping Firestore log (DB not initialized)", file=sys.stderr, flush=True)
        return
    
    try:
        db.collection("network_logs").add({
            **status_data,
            "logged_at": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        print(f"Error logging to Firestore: {e}", file=sys.stderr, flush=True)

def update_device_metrics(device_id, metrics):
    """Update device metrics in Firestore"""
    if db is None:
        print("Skipping device metrics update (DB not initialized)", file=sys.stderr, flush=True)
        return
    
    try:
        device_ref = db.collection("devices").document(device_id)
        device_ref.set({
            "last_checked": firestore.SERVER_TIMESTAMP,
            "metrics": metrics
        }, merge=True)
    except Exception as e:
        print(f"Error updating device metrics: {e}", file=sys.stderr, flush=True)


def watch_ai_requests():
    """Watch for pending AI requests and process them"""
    if db is None:
        print("Cannot watch AI requests (DB not initialized)", file=sys.stderr, flush=True)
        return
    
    print("Starting to watch for pending AI requests...", file=sys.stderr, flush=True)
    
    # document changes
    def on_snapshot(col_snapshot, changes, read_time):
        for change in changes:
            if change.type.name == 'ADDED':
                doc = change.document
                data = doc.to_dict()
                
                # Only process if status is pending
                if data.get('status') == 'pending':
                    print(f"Processing AI request: {doc.id}", file=sys.stderr, flush=True)
                    process_ai_request(doc.id, data)
    
    # Set up the listener
    query = db.collection('ai_requests').where(
    filter=FieldFilter('status', '==', 'pending'))
    query.on_snapshot(on_snapshot)

def process_ai_request(request_id, request_data):
    """Process a single AI request"""
    if db is None or client is None:
        print("Cannot process AI request (DB or client not initialized)", file=sys.stderr, flush=True)
        return
    
    start_time = time.time()
    
    try:
        # Check if request has expired
        expires_at = request_data.get('expires_at')
        if expires_at and expires_at < datetime.now(timezone.utc):
            print(f"Request {request_id} has expired", file=sys.stderr, flush=True)
            update_request_status(request_id, 'expired')
            return
        
        # Get the prompt from request
        prompt = request_data.get('prompt', '')
        if not prompt:
            raise ValueError("No prompt found in request")
        
        print(f"Sending prompt to Claude API...", file=sys.stderr, flush=True)
        
        # Call Claude API
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        ai_response = message.content[0].text
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        print(f"Received response from Claude ({processing_time_ms}ms)", file=sys.stderr, flush=True)
        
        # Extract suggestions from response
        suggestions = extract_suggestions(ai_response)
    
        
        # Write response to ai_responses collection
        response_doc = {
            "timestamp": firestore.SERVER_TIMESTAMP,
            "request_id": request_id,
            "device_id": request_data.get('device_id', 'unknown'),
            "response": ai_response,
            "success": True,
            "error": None,
            "suggestions": suggestions,
            "metadata": {
                "model": "claude-sonnet-4-5-20250929",
                "processing_time_ms": processing_time_ms,
                "tokens_used": message.usage.input_tokens + message.usage.output_tokens,
                "request_type": request_data.get('request_type', 'general_query')
            }
        }
        
        db.collection('ai_responses').add(response_doc)
        print(f"Wrote response to ai_responses collection", file=sys.stderr, flush=True)
        
        # Update original request status to completed
        update_request_status(request_id, 'completed')
        print(f"Request {request_id} completed successfully", file=sys.stderr, flush=True)
        
    except Exception as e:
        processing_time_ms = int((time.time() - start_time) * 1000)
        error_msg = str(e)
        print(f"Error processing request {request_id}: {error_msg}", file=sys.stderr, flush=True)
        
        # Write error response
        error_doc = {
            "timestamp": firestore.SERVER_TIMESTAMP,
            "request_id": request_id,
            "device_id": request_data.get('device_id', 'unknown'),
            "response": None,
            "success": False,
            "error": error_msg,
            "metadata": {
                "processing_time_ms": processing_time_ms,
                "error_type": type(e).__name__
            }
        }
        
        db.collection('ai_responses').add(error_doc)
        
        # Update request with error status and increment retry count
        db.collection('ai_requests').document(request_id).update({
            "status": "failed",
            "retry_count": firestore.Increment(1),
            "last_error": error_msg,
            "updated_at": firestore.SERVER_TIMESTAMP
        })

def update_request_status(request_id, status):
    """Update the status of an AI request"""
    if db is None:
        return
    
    try:
        db.collection('ai_requests').document(request_id).update({
            "status": status,
            "updated_at": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        print(f"Error updating request status: {e}", file=sys.stderr, flush=True)

def extract_suggestions(response_text):
    """Extract actionable suggestions from AI response"""
    suggestions = []
    lines = response_text.split('\n')
    
    for line in lines:
        # Match numbered lists, bullets, or lines with action words
        stripped = line.strip()
        if stripped and (
            stripped[0].isdigit() or 
            stripped.startswith(('-', '*', '•')) or
            any(word in stripped.lower() for word in ['try', 'check', 'enable', 'disable', 'restart', 'update'])
        ):
            # Cleaning the line
            cleaned = stripped.lstrip('0123456789.-*• ')
            if len(cleaned) > 10:  # Ignore very short lines
                suggestions.append(cleaned)
    
    return suggestions[:5]  # Return top 5 suggestions

def get_latest_ai_request():
    """Get the latest AI request from Firestore"""
    if db is None:
        return {}
    
    try:
        ai_requests = db.collection("ai_requests").order_by(
            "timestamp", direction=firestore.Query.DESCENDING
        ).limit(1).stream()
        
        latest_ai_request = next(ai_requests, None)
        if latest_ai_request:
            ai_data = latest_ai_request.to_dict()
            ai_data['request_id'] = latest_ai_request.id  
            return ai_data
        else:
            return {}
    except Exception as e:
        print(f"Error reading ai request logs: {e}", file=sys.stderr, flush=True)
        return {}

def get_latest_ai_response():
    """Get the latest AI response from Firestore"""
    if db is None:
        return {}
    
    try:
        ai_responses = db.collection("ai_responses").order_by(
            "timestamp", direction=firestore.Query.DESCENDING
        ).limit(1).stream()
        
        latest_ai_response = next(ai_responses, None)
        if latest_ai_response:
            response_data = latest_ai_response.to_dict()
            response_data['response_id'] = latest_ai_response.id
            return response_data
        else:
            return {}
    except Exception as e:
        print(f"Error reading ai response logs: {e}", file=sys.stderr, flush=True)
        return {}

@app.list_tools()
async def list_tools() -> list[Tool]:
    """Define available tools"""
    return [
        Tool(
            name="get_network_status",
            description="Get current network status including signal strength and device count",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_device_metrics",
            description="Get detailed metrics for a specific device",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Device name: router, living_room_tv, office_pc"
                    }
                },
                "required": ["device_id"]
            }
        ),
        Tool(
            name="list_devices",
            description="List all devices from Firestore database",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="diagnose_connection",
            description="Get troubleshooting recommendations for network issues",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Optional device to diagnose"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_network_health_dashboard",
            description="Get comprehensive network health score, issues, and recommendations",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_latest_ai_request",
            description="Get the most recent AI request from the database",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_latest_ai_response",
            description="Get the most recent AI response from the database",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="process_pending_requests",
            description="Manually trigger processing of all pending AI requests",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool execution"""
    try:
        if name == "get_network_status":
            devices = get_devices_from_db()
            
            data = {
                "timestamp": datetime.now(timezone.utc),
                "network": {
                    "5g_signal": f"{random.randint(70, 95)}%",
                },
                "active_devices": len([d for d in devices.values() if d.get("status") == "online"]),
                "status": "healthy"
            }
            
            log_network_status(data)
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        
        elif name == "get_device_metrics":
            device_id = arguments.get("device_id", "")
            devices = get_devices_from_db()
            
            if device_id not in devices:
                available = ", ".join(devices.keys())
                return [TextContent(
                    type="text",
                    text=f"Device '{device_id}' not found. Available: {available}"
                )]
            
            metrics = {
                "is_active": random.choice([True, False]),
                "sessions_today": random.randint(0, 5),
                "data_used_gb": round(random.uniform(0, 12), 2)
            }
            
            data = {
                "device_id": device_id,
                "info": devices[device_id],
                "activity": metrics
            }
            
            update_device_metrics(device_id, metrics)
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        
        elif name == "list_devices":
            devices_data = get_devices_from_db()
            
            data = {
                "timestamp": datetime.now(timezone.utc),
                "total_devices": len(devices_data),
                "devices": devices_data,
                "source": "firestore" if db else "fallback"
            }
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        
        elif name == "diagnose_connection":
            device_id = arguments.get("device_id", "general")
            
            data = {
                "device_id": device_id,
                "timestamp": datetime.now(timezone.utc),
                "findings": ["Peak usage detected: 3 devices streaming simultaneously"],
                "likely_causes": ["Possible interference from neighboring networks"],
                "recommendations": [
                    "Enable QoS to prioritize video calls over streaming",
                    "Check for firmware updates for router"
                ],
                "immediate_actions": [
                    "Reduce streaming quality temporarily",
                    "Check for bandwidth-heavy background updates"
                ]
            }
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        
        elif name == "get_network_health_dashboard":
            # Try to get latest network log from Firestore
            if db:
                try:
                    network_logs = db.collection("network_logs").order_by(
                        "logged_at", direction=firestore.Query.DESCENDING
                    ).limit(1).stream()
                    
                    latest_network = next(network_logs, None)
                    
                    if latest_network:
                        net = latest_network.to_dict()
                    else:
                        net = {}
                except Exception as e:
                    print(f"Error reading network logs: {e}", file=sys.stderr, flush=True)
                    net = {}
            else:
                net = {}
            
            # Extract or generate metrics
            current = {
                "ping_ms": net.get("ping_ms", random.randint(20, 50)),
                "jitter_ms": net.get("jitter_ms", random.randint(1, 5)),
                "download_mbps": net.get("download_mbps", random.randint(25, 100)),
                "upload_mbps": net.get("upload_mbps", random.randint(10, 50)),
                "packet_loss_percent": net.get("packet_loss_percent", 0),
                "wifi_rssi_dbm": net.get("wifi_rssi_dbm", random.randint(-70, -50)),
                "temperature_c": net.get("temperature_c", random.randint(45, 65)),
                "active_devices": net.get("active_devices", 3)
            }
            
            # Calculate health score (0-100)
            health_score = 100
            issues = []
            recommendations = []
            
            # Evaluate metrics
            if current["ping_ms"] > 100:
                health_score -= 20
                issues.append(f"High latency: {current['ping_ms']}ms")
                recommendations.append("Check for bandwidth-heavy applications")
            
            if current["jitter_ms"] > 10:
                health_score -= 15
                issues.append(f"High jitter: {current['jitter_ms']}ms")
                recommendations.append("Enable QoS on router")
            
            if current["download_mbps"] < 10:
                health_score -= 25
                issues.append(f"Low download speed: {current['download_mbps']}Mbps")
                recommendations.append("Run speed test to verify ISP speed")
            
            if current["upload_mbps"] < 5:
                health_score -= 20
                issues.append(f"Low upload speed: {current['upload_mbps']}Mbps")
                recommendations.append("Contact ISP if consistently low")
            
            if current["packet_loss_percent"] > 1:
                health_score -= 30
                issues.append(f"Packet loss: {current['packet_loss_percent']}%")
                recommendations.append("Check cable connections and restart router")
            
            if current["wifi_rssi_dbm"] < -70:
                health_score -= 15
                issues.append(f"Weak WiFi signal: {current['wifi_rssi_dbm']}dBm")
                recommendations.append("Move closer to router or use WiFi extender")
            
            if current["temperature_c"] > 70:
                health_score -= 10
                issues.append(f"High temperature: {current['temperature_c']}°C")
                recommendations.append("Ensure proper ventilation around router")
            
            # Determine status
            health_score = max(0, health_score)
            
            if health_score >= 90:
                status = "excellent"
                summary = "Your network is performing optimally!"
            elif health_score >= 70:
                status = "good"
                summary = "Your network is performing well"
            elif health_score >= 50:
                status = "fair"
                summary = "Your network has some issues that should be addressed"
            else:
                status = "poor"
                summary = "Your network has significant issues requiring attention"
            
            # Build dashboard
            dashboard = {
                "timestamp": datetime.now(timezone.utc),
                "health_score": health_score,
                "status": status,
                "summary": summary,
                "current_metrics": current,
                "issues": issues if issues else ["No issues detected"],
                "recommendations": recommendations if recommendations else ["No recommendations at this time"]
            }
            
            return [TextContent(type="text", text=json.dumps(dashboard, indent=2))]
        
        elif name == "get_latest_ai_request":
            ai_request = get_latest_ai_request()
            return [TextContent(type="text", text=json.dumps(ai_request, indent=2, default=str))]
        
        elif name == "get_latest_ai_response":
            ai_response = get_latest_ai_response()
            return [TextContent(type="text", text=json.dumps(ai_response, indent=2, default=str))]
        
        elif name == "process_pending_requests":
            if db is None:
                return [TextContent(type="text", text="Database not initialized")]
            
            # Get all pending requests
            pending = db.collection('ai_requests').where('status', '==', 'pending').stream()
            count = 0
            
            for doc in pending:
                process_ai_request(doc.id, doc.to_dict())
                count += 1
            
            return [TextContent(type="text", text=f"Processed {count} pending request(s)")]
        
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    except Exception as e:
        error_msg = f"Error executing {name}: {str(e)}"
        print(error_msg, file=sys.stderr, flush=True)
        return [TextContent(type="text", text=error_msg)]

async def main():
    """Start the MCP server"""
    print("Starting Home Network Copilot MCP Server...", file=sys.stderr, flush=True)
    
    if db is not None:
        watch_ai_requests()
    
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
