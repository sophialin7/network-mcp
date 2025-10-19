import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
import random

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

cred = credentials.Certificate('Users/slin7/Documents/home-network-mcp/pulseone-dh-firebase-adminsdk-fbsvc-961957f988.json')
firebase_app = firebase_admin.initialize_app(cred)
db = firestore.client()

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("Error: MCP not installed. Run: pip install mcp")
    exit(1)


# Initialize MCP server
app = Server("home-network-copilot")

# Default fallback devices (used if Firestore is empty or fails)
DEFAULT_DEVICES = {
    "router": {"type": "gateway", "location": "office", "status": "online"},
    "living_room_tv": {"type": "streaming", "location": "living_room", "status": "online"},
    "office_pc": {"type": "workstation", "location": "office", "status": "online"}
}

# Helper function to get devices from Firestore
def get_devices_from_db():
    """Fetch devices from Firestore"""
    try:
        devices_ref = db.collection("devices")
        docs = devices_ref.stream()
        
        devices = {}
        for doc in docs:
            devices[doc.id] = doc.to_dict()
        
        # Fallback to default devices if none in Firestore
        if not devices:
            print("No devices found in Firestore, using defaults")
            devices = DEFAULT_DEVICES
        else:
            print(f"Loaded {len(devices)} devices from Firestore")
        
        return devices
    except Exception as e:
        print(f"Error fetching devices from Firestore: {e}")
        # Return default devices on error
        return DEFAULT_DEVICES

# Helper function to log network status to Firestore
def log_network_status(status_data):
    """Log network status to Firestore for historical tracking"""
    try:
        db.collection("network_logs").add({
            **status_data,
            "logged_at": firestore.SERVER_TIMESTAMP
        })
    except Exception as e:
        print(f"Error logging to Firestore: {e}")

# Helper function to get user preferences from Firestore
def get_user_preferences(user_id="default"):
    """Get user preferences from Firestore"""
    try:
        user_ref = db.collection("users").document(user_id)
        user_doc = user_ref.get()
        
        if user_doc.exists:
            return user_doc.to_dict()
        return {}
    except Exception as e:
        print(f"Error fetching user preferences: {e}")
        return {}

# Helper function to update device metrics in Firestore
def update_device_metrics(device_id, metrics):
    """Update device metrics in Firestore"""
    try:
        device_ref = db.collection("devices").document(device_id)
        device_ref.set({
            "last_checked": firestore.SERVER_TIMESTAMP,
            "metrics": metrics
        }, merge=True)
    except Exception as e:
        print(f"Error updating device metrics: {e}")

# Read initial data on startup
print("Checking Firebase connection...")
try:
    users_ref = db.collection("users")
    docs = users_ref.stream()
    
    user_count = 0
    for doc in docs:
        print(f"User: {doc.id} => {doc.to_dict()}")
        user_count += 1
    
    if user_count == 0:
        print("No users found in Firestore")
    
    # Also check devices
    devices_data = get_devices_from_db()
    print(f"Initial device check: {list(devices_data.keys())}")
except Exception as e:
    print(f"Error connecting to Firebase: {e}")

@app.list_tools()
async def list_tools() -> list[Tool]:
    """Tools for the AI assistant"""
    return [
        Tool(
            name="get_network_status",
            description="Get current network status including signal strength, temperature, and device count",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_device_metrics",
            description="Get detailed metrics for a specific device (bandwidth)",
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
            name="diagnose_connection",
            description="Analye network connection and get troubleshooting recommendations",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Receive guidance for troubleshooting recommendations"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="list_devices",
            description="List all devices from Firestore database with their details",
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
            # Get devices from Firebase for accurate count
            devices = get_devices_from_db()
            
            data = {
                "timestamp": datetime.now().isoformat(),
                "network": {
                    "5g_signal": f"{random.randint(70, 95)}%",
                },
                "active_devices": len([d for d in devices.values() if d.get("status") == "online"]),
                "status": "healthy"
            }
            
            # Log to Firestore
            log_network_status(data)
            
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        
        elif name == "get_device_metrics":
            device_id = arguments.get("device_id", "")
            
            # Get devices from Firebase
            devices = get_devices_from_db()
            
            # Get devices from Firebase
            devices = get_devices_from_db()
            
            if device_id not in devices:
                available = ", ".join(devices.keys())
                return [TextContent(
                    type="text",
                    text=f"Device '{device_id}' not found. Available devices: {available}"
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
            
            # Update metrics in Firestore
            update_device_metrics(device_id, metrics)
            
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        
        elif name == "diagnose_connection":
            device_id = arguments.get("device_id", "general")
            
            data = {
                "device_id": device_id,
                "issue_reported": arguments.get("issue", "general check"),
                "timestamp": datetime.now().isoformat(),
                "findings": [
                    "Peak usage detected: 3 devices streaming simultaneously"
                ],
                "likely_causes": [
                    "Possible interference from neighboring networks"
                ],
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
        
        elif name == "list_devices":
            devices_data = get_devices_from_db()
            
            data = {
                "timestamp": datetime.now().isoformat(),
                "total_devices": len(devices_data),
                "devices": devices_data,
                "source": "firestore"
            }
            return [TextContent(type="text", text=json.dumps(data, indent=2))]
        
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    
    except Exception as e:
        error_msg = f"Error executing {name}: {str(e)}"
        print(error_msg)
        return [TextContent(type="text", text=error_msg)]

async def main():
    """Start the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    print("Starting Home Network Copilot MCP Server...", flush=True)
    asyncio.run(main())
