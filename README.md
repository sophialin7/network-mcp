NetPulse: Intelligent Edge-AI for Real Time Network Anomaly Detection

* Install IDEs and Tools:
Arduino IDE
Claude Desktop

For Firmware
 * 1. Install "DHT sensor library" by Adafruit
 * 2. Install "Adafruit Unified Sensor" library
 * 3. Upload firmware at `max-firmware` to your Arduino Uno
 * 4. Open Serial Monitor at 9600 baud
 */

 For MCP Server
 1. Install anthropic by `pip install anthropic`
 2. Install firebase admin by `pip install firebase-admin` to use the Firebase Admin SDK
 3. Setup virtual environment
 5. Create a new project and upload only `server.py`
 6. Ensure firebaseadmin.json file with key is inside the same folder as `server.py`
 7. Ensure package-lock.json and package.json is inside same folder as `server.py`
 8. Configure project with `claude_desktop_config.json file` with the following format below:
  "mcpServers": {
    "home-network-copilot": {
      "command": "/Users/<user>/path/to/venv/bin/python3",
      "args": ["/Users/<user>/path/to/server.py"]
    }
  }
}
9. Interact with chat interface to ask sample prompts like:
What is my network health status?
How can I optimize my network performance?
