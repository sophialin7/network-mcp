# MCP Server Quick Reference Card

## TL;DR for Server Developer

You need to:
1. **Watch** Firestore collection `ai_requests` for documents where `status == "pending"`
2. **Process** the `prompt` field with Claude/OpenAI
3. **Write** response to `ai_responses` collection with matching `request_id`
4. **Update** the original request's `status` to `"completed"`

---

## Input: `ai_requests` Collection

### Document You'll Receive:
```javascript
{
  "timestamp": Timestamp,
  "request_type": "general_query" | "analyze_anomaly" | "suggest_healing" | "analyze_correlations",
  "status": "pending",
  "device_id": "iphone_app",
  "prompt": "The full AI prompt text here...",
  "expires_at": Timestamp,
  "retry_count": 0
}
```

**Your job:** Read the `prompt` field and send it to your AI API.

---

## Output: `ai_responses` Collection

### Document You Must Create:
```javascript
{
  "timestamp": FieldValue.serverTimestamp(),
  "request_id": "<documentID from ai_requests>",
  "device_id": "iphone_app",
  "response": "Your AI's response text here...",
  "success": true,
  "error": null,

  // Optional but recommended:
  "confidence": 0.95,
  "suggestions": ["Action 1", "Action 2", "Action 3"],
  "metadata": {
    "model": "claude-3-5-sonnet",
    "processing_time_ms": "1234"
  }
}
```

---

## Python Template (5-Minute Setup)

```python
import firebase_admin
from firebase_admin import credentials, firestore
import anthropic

# Initialize
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()
client = anthropic.Anthropic(api_key="your-key")

# Watch for requests
def on_snapshot(doc_snapshot, changes, read_time):
    for change in changes:
        if change.type.name in ['ADDED', 'MODIFIED']:
            doc = change.document
            data = doc.to_dict()

            if data.get('status') == 'pending':
                process_request(doc.id, data)

# Process request
def process_request(request_id, request_data):
    try:
        # Update status
        db.collection('ai_requests').document(request_id).update({
            'status': 'processing',
            'processed_at': firestore.SERVER_TIMESTAMP
        })

        # Call Claude
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            messages=[{"role": "user", "content": request_data['prompt']}]
        )

        response_text = message.content[0].text

        # Save response
        db.collection('ai_responses').add({
            'timestamp': firestore.SERVER_TIMESTAMP,
            'request_id': request_id,
            'device_id': request_data['device_id'],
            'response': response_text,
            'success': True,
            'error': None
        })

        # Mark complete
        db.collection('ai_requests').document(request_id).update({
            'status': 'completed',
            'completed_at': firestore.SERVER_TIMESTAMP
        })

    except Exception as e:
        # Save error response
        db.collection('ai_responses').add({
            'timestamp': firestore.SERVER_TIMESTAMP,
            'request_id': request_id,
            'device_id': request_data.get('device_id'),
            'response': '',
            'success': False,
            'error': str(e)
        })

# Start watching
query = db.collection('ai_requests').where('status', '==', 'pending')
query_watch = query.on_snapshot(on_snapshot)

# Keep running
import time
while True:
    time.sleep(1)
```

---

## Node.js Template (Alternative)

```javascript
const admin = require('firebase-admin');
const Anthropic = require('@anthropic-ai/sdk');

admin.initializeApp({
  credential: admin.credential.cert(require('./serviceAccountKey.json'))
});

const db = admin.firestore();
const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

// Watch for requests
db.collection('ai_requests')
  .where('status', '==', 'pending')
  .onSnapshot(async (snapshot) => {
    snapshot.docChanges().forEach(async (change) => {
      if (change.type === 'added' || change.type === 'modified') {
        const doc = change.doc;
        await processRequest(doc.id, doc.data());
      }
    });
  });

async function processRequest(requestId, requestData) {
  try {
    // Update status
    await db.collection('ai_requests').doc(requestId).update({
      status: 'processing',
      processed_at: admin.firestore.FieldValue.serverTimestamp()
    });

    // Call Claude
    const message = await anthropic.messages.create({
      model: 'claude-3-5-sonnet-20241022',
      max_tokens: 2048,
      messages: [{ role: 'user', content: requestData.prompt }]
    });

    const responseText = message.content[0].text;

    // Save response
    await db.collection('ai_responses').add({
      timestamp: admin.firestore.FieldValue.serverTimestamp(),
      request_id: requestId,
      device_id: requestData.device_id,
      response: responseText,
      success: true,
      error: null
    });

    // Mark complete
    await db.collection('ai_requests').doc(requestId).update({
      status: 'completed',
      completed_at: admin.firestore.FieldValue.serverTimestamp()
    });

  } catch (error) {
    await db.collection('ai_responses').add({
      timestamp: admin.firestore.FieldValue.serverTimestamp(),
      request_id: requestId,
      device_id: requestData.device_id,
      response: '',
      success: false,
      error: error.message
    });
  }
}

console.log('MCP Server running...');
```

---

## What iOS App Does

1. User taps button → iOS writes to `ai_requests`
2. iOS listens to `ai_responses` for matching `request_id`
3. iOS waits max 60 seconds for response
4. When response arrives, iOS displays it to user

---

## Field Details

### Required Fields in `ai_responses`:
- ✅ `timestamp` - When response created
- ✅ `request_id` - Must match document ID from `ai_requests`
- ✅ `device_id` - Copy from request (usually "iphone_app")
- ✅ `response` - Your AI's text response
- ✅ `success` - `true` if worked, `false` if error
- ❌ `error` - Only if `success` is `false`

### Optional But Nice:
- `confidence` - Number 0.0-1.0 (how confident the AI is)
- `suggestions` - Array of action items (e.g., ["Restart WiFi", "Check cables"])
- `metadata` - Object with `{model: "claude-3.5", processing_time_ms: "1234"}`

---

## Example Request You'll Receive

```json
{
  "timestamp": "2025-10-19T02:30:00Z",
  "request_type": "general_query",
  "status": "pending",
  "device_id": "iphone_app",
  "prompt": "Perform a general health check analysis of the PulseOne network monitoring system.\n\nPlease provide:\n1. Overall system status assessment\n2. Any potential concerns or areas to monitor\n3. Recommendations for optimal performance\n4. General network health tips\n\nKeep the response concise and actionable.",
  "expires_at": "2025-10-19T02:40:00Z",
  "retry_count": 0
}
```

**Your response:**
```json
{
  "timestamp": "2025-10-19T02:30:15Z",
  "request_id": "abc123xyz",
  "device_id": "iphone_app",
  "response": "## System Health Assessment\n\n**Overall Status**: Good\n\nYour network is stable with average ping of 45ms...",
  "success": true,
  "error": null,
  "suggestions": ["Monitor packet loss", "Set alerts for latency > 100ms"],
  "metadata": {
    "model": "claude-3-5-sonnet",
    "processing_time_ms": "1234"
  }
}
```

---

## Setup Checklist

- [ ] Firebase Admin SDK installed
- [ ] Service account key downloaded (`.json` file)
- [ ] Claude API key obtained
- [ ] Can connect to Firestore (test read/write)
- [ ] Script watches `ai_requests` collection
- [ ] Script writes to `ai_responses` collection
- [ ] Error handling implemented
- [ ] Server running continuously (systemd/pm2/screen)

---

## Testing

1. **Test Firestore connection:**
   ```python
   db.collection('test').add({'hello': 'world'})
   ```

2. **Test AI API:**
   ```python
   message = client.messages.create(
       model="claude-3-5-sonnet-20241022",
       max_tokens=100,
       messages=[{"role": "user", "content": "Say hi"}]
   )
   print(message.content[0].text)
   ```

3. **Test end-to-end:**
   - Run your server
   - Use iOS app to send request
   - Check logs on server
   - Verify response appears in Firestore
   - Verify iOS app displays response

---

## Troubleshooting

**Server not seeing requests?**
- Check Firestore rules allow read access
- Verify watching correct collection name (`ai_requests`)
- Check filter is correct (`status == "pending"`)

**Responses not appearing in iOS?**
- Verify `request_id` matches exactly
- Check Firestore rules allow writes to `ai_responses`
- Ensure `device_id` is copied from request

**Claude API errors?**
- Check API key is valid
- Verify rate limits not exceeded
- Check internet connection

---

## Support Files

- Full spec: `MCP_API_SPECIFICATION.md`
- Debugging: `FIRESTORE_DEBUGGING.md`
- Setup guide: `MCP_SERVER_GUIDE.md`
