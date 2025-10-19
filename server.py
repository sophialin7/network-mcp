import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
import random
import sys

import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Initialize Firebase
db = None
try:
    cred = credentials.Certificate('pulseone-dh-firebase-adminsdk-fbsvc-961957f988.json')
    firebase_app = firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase initialized successfully", file=sys.stderr, flush=True)
except Exception as e:
    print(f"Warning: Firebase initialization failed: {e}", file=sys.stderr, flush=True)

# Configuration
NETWORK_ID = "home"
DEMO_MODE = True  # true only for demo

app = Server("home-network-copilot")

DEFAULT_DEVICES = {
    "router": {"type": "gateway", "location": "office", "status": "online"},
    "living_room_tv": {"type": "streaming", "location": "living_room", "status": "online"},
    "office_pc": {"type": "workstation", "location": "office", "status": "online"}
}

# Demo network scenarios
DEMO_NETWORKS = {
    "home": {
        "name": "Home Network",
        "health_range": (85, 100),
        "metrics": {
            "ping_ms": (20, 50),
            "jitter_ms": (1, 8),
            "download_mbps": (75, 100),
            "upload_mbps": (25, 50),
            "packet_loss_percent": (0, 0.5),
            "wifi_rssi_dbm": (-65, -50),
            "temperature_c": (45, 65),
            "active_devices": (2, 4)
        }
    },
    "office": {
        "name": "Office Network",
        "health_range": (70, 90),
        "metrics": {
            "ping_ms": (30, 80),
            "jitter_ms": (3, 10),
            "download_mbps": (40, 80),
            "upload_mbps": (15, 35),
            "packet_loss_percent": (0, 1),
            "wifi_rssi_dbm": (-70, -55),
            "temperature_c": (50, 68),
            "active_devices": (5, 8)
        }
    },
    "cabin": {
        "name": "Vacation Cabin",
        "health_range": (50, 70),
        "metrics": {
            "ping_ms": (80, 130),
            "jitter_ms": (8, 15),
            "download_mbps": (8, 25),
            "upload_mbps": (3, 10),
            "packet_loss_percent": (0.5, 2),
            "wifi_rssi_dbm": (-80, -65),
            "temperature_c": (55, 72),
            "active_devices": (2, 5)
        }
    },
    "coffee_shop": {
        "name": "Coffee Shop WiFi",
        "health_range": (20, 50),
        "metrics": {
            "ping_ms": (100, 200),
            "jitter_ms": (15, 30),
            "download_mbps": (2, 15),
            "upload_mbps": (1, 5),
            "packet_loss_percent": (2, 5),
            "wifi_rssi_dbm": (-85, -70),
            "temperature_c": (60, 75),
            "active_devices": (10, 25)
        }
    }
}

def generate_demo_metrics(network_id):
    """Generate realistic demo metrics for a network"""
    if network_id not in DEMO_NETWORKS:
        network_id = "home"
    
    config = DEMO_NETWORKS[network_id]
    metrics = {}
    
    for key, (min_val, max_val) in config["metrics"].items():
        if isinstance(min_val, int) and isinstance(max_val, int):
            metrics[key] = random.randint(min_val, max_val)
        else:
            metrics[key] = round(random.uniform(min_val, max_val), 2)
    return metrics

def calculate_health_score(metrics):
    """Calculate health score based on metrics"""
    health_score = 100
    issues = []
    recommendations = []
    
    if metrics["ping_ms"] > 100:
        health_score -= 20
        issues.append(f"High latency: {metrics['ping_ms']}ms")
        recommendations.append("Check for bandwidth-heavy applications")
    
    if metrics["jitter_ms"] > 10:
        health_score -= 15
        issues.append(f"High jitter: {metrics['jitter_ms']}ms")
        recommendations.append("Enable QoS on router")
    
    if metrics["download_mbps"] < 10:
        health_score -= 25
        issues.append(f"Low download speed: {metrics['download_mbps']}Mbps")
        recommendations.append("Run speed test to verify ISP speed")
    
    if metrics["upload_mbps"] < 5:
        health_score -= 20
        issues.append(f"Low upload speed: {metrics['upload_mbps']}Mbps")
        recommendations.append("Contact ISP if consistently low")
    
    if metrics["packet_loss_percent"] > 1:
        health_score -= 30
        issues.append(f"Packet loss: {metrics['packet_loss_percent']}%")
        recommendations.append("Check cable connections and restart router")
    
    if metrics["wifi_rssi_dbm"] < -70:
        health_score -= 15
        issues.append(f"Weak WiFi signal: {metrics['wifi_rssi_dbm']}dBm")
        recommendations.append("Move closer to router or use WiFi extender")
    
    if metrics["temperature_c"] > 70:
        health_score -= 10
        issues.append(f"High temperature: {metrics['temperature_c']}°C")
        recommendations.append("Ensure proper ventilation around router")
    
    health_score = max(0, health_score)
    
    if health_score >= 90:
        status = "excellent"
        summary = "Network is performing optimally!"
    elif health_score >= 70:
        status = "good"
        summary = "Network is performing well"
    elif health_score >= 50:
        status = "fair"
        summary = "Network has some issues that should be addressed"
    else:
        status = "poor"
        summary = "Network has significant issues requiring attention"
    
    return health_score, status, summary, issues, recommendations

@app.list_tools()
async def list_tools() -> list[Tool]:
    """Define available tools"""
    return [
        Tool(
            name="list_networks",
            description="List all available networks being monitored",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="get_network_status",
            description="Get current network status including signal strength and device count",
            inputSchema={
                "type": "object",
                "properties": {
                    "network_id": {
                        "type": "string",
                        "description": "Network identifier: home, office, cabin, coffee_shop"
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
                "properties": {
                    "network_id": {
                        "type": "string",
                        "description": "Network identifier: home, office, cabin, coffee_shop"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="compare_networks",
            description="Compare health scores across all monitored networks",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": []
            }
        ),
        Tool(
            name="find_worst_network",
            description="Find the network with the lowest health score",
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
                    },
                    "network_id": {
                        "type": "string",
                        "description": "Optional: Network identifier"
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
                "properties": {
                    "network_id": {
                        "type": "string",
                        "description": "Optional: Network identifier"
                    }
                },
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
                    },
                    "network_id": {
                        "type": "string",
                        "description": "Optional: Network identifier"
                    }
                },
                "required": []
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: Any) -> list[TextContent]:
    """Handle tool execution"""
    if name == "list_networks":
        if DEMO_MODE:
            networks = list(DEMO_NETWORKS.keys())
            data = {
                "timestamp": datetime.now().isoformat(),
                "mode": "demo",
                "networks": [
                    {
                        "id": net_id,
                        "name": DEMO_NETWORKS[net_id]["name"]
                    }
                    for net_id in networks
                ],
                "current_network": NETWORK_ID,
                "total_count": len(networks)
            }
        else:
            data = {
                "timestamp": datetime.now().isoformat(),
                "mode": "production",
                "networks": [{"id": NETWORK_ID, "name": "Current Network"}],
                "total_count": 1
            }
        return [TextContent(type="text", text=json.dumps(data, indent=2))]
    
    elif name == "compare_networks":
        if not DEMO_MODE:
            return [TextContent(type="text", text="Demo mode not enabled. Only one network available.")]
        
        comparison = {
            "timestamp": datetime.now().isoformat(),
            "mode": "demo",
            "networks": {}
        }
        
        for net_id, config in DEMO_NETWORKS.items():
            metrics = generate_demo_metrics(net_id)
            health_score, status, summary, issues, recommendations = calculate_health_score(metrics)
            
            comparison["networks"][net_id] = {
                "name": config["name"],
                "health_score": health_score,
                "status": status,
                "summary": summary,
                "key_metrics": {
                    "ping_ms": metrics["ping_ms"],
                    "download_mbps": metrics["download_mbps"],
                    "upload_mbps": metrics["upload_mbps"],
                    "active_devices": metrics["active_devices"]
                },
                "issue_count": len([i for i in issues if i != "No issues detected"])
            }
        
        return [TextContent(type="text", text=json.dumps(comparison, indent=2))]
    
    elif name == "find_worst_network":
        if not DEMO_MODE:
            return [TextContent(type="text", text="Demo mode not enabled. Only one network available.")]
        
        worst_score = 100
        worst_network = None
        all_networks = {}
        
        for net_id, config in DEMO_NETWORKS.items():
            metrics = generate_demo_metrics(net_id)
            health_score, status, summary, issues, recommendations = calculate_health_score(metrics)
            
            all_networks[net_id] = {
                "name": config["name"],
                "health_score": health_score,
                "status": status,
                "metrics": metrics,
                "issues": issues,
                "recommendations": recommendations
            }
            
            if health_score < worst_score:
                worst_score = health_score
                worst_network = net_id
    
        if worst_network:
            result = {
                "timestamp": datetime.now().isoformat(),
                "worst_network": {
                    "id": worst_network,
                    **all_networks[worst_network]
                },
                "all_networks_ranked": sorted(
                    [
                        {"id": net_id, "name": data["name"], "health_score": data["health_score"]}
                        for net_id, data in all_networks.items()
                    ],
                    key=lambda x: x["health_score"]
                )
            }
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    elif name == "get_network_status":
        network_id = arguments.get("network_id", NETWORK_ID)
        
        if DEMO_MODE and network_id not in DEMO_NETWORKS:
            available = ", ".join(DEMO_NETWORKS.keys())
            return [TextContent(
                type="text",
                text=f"Network '{network_id}' not found. Available: {available}"
            )]
        
        metrics = generate_demo_metrics(network_id) if DEMO_MODE else {}
        
        data = {
            "timestamp": datetime.now().isoformat(),
            "network_id": network_id,
            "network_name": DEMO_NETWORKS[network_id]["name"] if DEMO_MODE and network_id in DEMO_NETWORKS else "Current Network",
            "mode": "demo" if DEMO_MODE else "production",
            "network": {
                "5g_signal": f"{random.randint(70, 95)}%",
            },
            "active_devices": metrics.get("active_devices", 3),
            "status": "healthy"
        }
        
        return [TextContent(type="text", text=json.dumps(data, indent=2))]
    
    elif name == "get_network_health_dashboard":    
        network_id = arguments.get("network_id", NETWORK_ID)
        
        if DEMO_MODE:
            if network_id not in DEMO_NETWORKS:
                available = ", ".join(DEMO_NETWORKS.keys())
                return [TextContent(
                    type="text",
                    text=f"Network '{network_id}' not found. Available: {available}"
                )]
            
            metrics = generate_demo_metrics(network_id)
        else:
            if db:
                try:
                    network_logs = db.collection("network_logs")\
                        .order_by("logged_at", direction=firestore.Query.DESCENDING)\
                        .limit(1).stream()
                    latest_network = next(network_logs, None)
                    net = latest_network.to_dict() if latest_network else {}
                except Exception as e:
                    net = {}
            else:
                net = {}
            
            metrics = {
                "ping_ms": net.get("ping_ms", random.randint(20, 50)),
                "jitter_ms": net.get("jitter_ms", random.randint(1, 5)),
                "download_mbps": net.get("download_mbps", random.randint(25, 100)),
                "upload_mbps": net.get("upload_mbps", random.randint(10, 50)),
                "packet_loss_percent": net.get("packet_loss_percent", 0),
                "wifi_rssi_dbm": net.get("wifi_rssi_dbm", random.randint(-70, -50)),
                "temperature_c": net.get("temperature_c", random.randint(45, 65)),
                "active_devices": net.get("active_devices", 3)
            }
        
        health_score, status, summary, issues, recommendations = calculate_health_score(metrics)
        
        dashboard = {
            "timestamp": datetime.now().isoformat(),
            "network_id": network_id,
            "network_name": DEMO_NETWORKS[network_id]["name"] if DEMO_MODE and network_id in DEMO_NETWORKS else "Current Network",
            "mode": "demo" if DEMO_MODE else "production",
            "health_score": health_score,
            "status": status,
            "summary": summary,
            "current_metrics": metrics,
            "issues": issues if issues else ["No issues detected"],
            "recommendations": recommendations if recommendations else ["No recommendations at this time"]
        }
            
        return [TextContent(type="text", text=json.dumps(dashboard, indent=2))]
    
    elif name == "get_device_metrics":
        device_id = arguments.get("device_id", "")
        network_id = arguments.get("network_id", NETWORK_ID)
        
        if device_id not in DEFAULT_DEVICES:
            available = ", ".join(DEFAULT_DEVICES.keys())
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
            "network_id": network_id,
            "device_id": device_id,
            "info": DEFAULT_DEVICES[device_id],
            "activity": metrics
        }
        
        return [TextContent(type="text", text=json.dumps(data, indent=2))]
    
    elif name == "list_devices":
        data = {
            "timestamp": datetime.now().isoformat(),
            "network_id": arguments.get("network_id", NETWORK_ID),
            "total_devices": len(DEFAULT_DEVICES),
            "devices": DEFAULT_DEVICES,
            "source": "demo" if DEMO_MODE else "fallback"
        }
        return [TextContent(type="text", text=json.dumps(data, indent=2))]
    
    elif name == "diagnose_connection":
        network_id = arguments.get("network_id", NETWORK_ID)
        device_id = arguments.get("device_id", "general")
        
        data = {
            "network_id": network_id,
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
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
    
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

async def main():
    """Start the MCP server"""
    mode = "DEMO MODE" if DEMO_MODE else "PRODUCTION"
    print(f"Starting NetPulse MCP Server [{mode}] for network: {NETWORK_ID}...", file=sys.stderr, flush=True)
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
