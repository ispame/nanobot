# Android 客户端修改指南

## 音频录制参数

修改录音配置，确保格式正确：

```kotlin
// 音频格式配置
private val SAMPLE_RATE = 16000  // 16kHz
private val CHANNEL_CONFIG = AudioFormat.CHANNEL_IN_MONO  // 单声道
private val AUDIO_FORMAT = AudioFormat.ENCODING_PCM_16BIT  // 16-bit
private val CHUNK_DURATION_MS = 100  // 100ms per chunk

// 计算 buffer 大小
private val BUFFER_SIZE = SAMPLE_RATE * 2 * CHUNK_DURATION_MS / 1000  // 3200 bytes
```

## 消息协议

### 1. 开始录音
```kotlin
fun startRecording() {
    val message = JSONObject().apply {
        put("type", "start_stream")
    }
    webSocket.send(message.toString())
}
```

### 2. 发送音频数据
```kotlin
fun sendAudioChunk(audioData: ByteArray, seq: Int) {
    val base64Data = Base64.encodeToString(audioData, Base64.NO_WRAP)
    val message = JSONObject().apply {
        put("type", "audio_data")
        put("data", base64Data)
        put("seq", seq)
    }
    webSocket.send(message.toString())
}
```

### 3. 结束录音
```kotlin
fun stopRecording() {
    val message = JSONObject().apply {
        put("type", "end_stream")
    }
    webSocket.send(message.toString())
}
```

## 接收服务器消息

```kotlin
override fun onMessage(webSocket: WebSocket, text: String) {
    val json = JSONObject(text)
    when (json.getString("type")) {
        "stream_ready" -> startAudioCapture()
        "asr_partial" -> updateUI(json.getString("text"), isPartial = true)
        "asr_final" -> updateUI(json.getString("text"), isPartial = false)
        "message" -> showResponse(json.getString("content"))
        "error" -> showError(json.getString("message"))
    }
}
```

## 完整录音流程

```kotlin
class AudioRecorder(private val webSocket: WebSocket) {
    private var audioRecord: AudioRecord? = null
    private var isRecording = false
    private var seq = 0

    fun start() {
        sendStartStream()
        audioRecord = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE, CHANNEL_CONFIG, AUDIO_FORMAT, BUFFER_SIZE * 2
        )
        isRecording = true
        seq = 0
        audioRecord?.startRecording()
        
        Thread {
            val buffer = ByteArray(BUFFER_SIZE)
            while (isRecording) {
                val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                if (read > 0) {
                    sendAudioChunk(buffer.copyOf(read), ++seq)
                }
            }
        }.start()
    }

    fun stop() {
        isRecording = false
        audioRecord?.stop()
        audioRecord?.release()
        sendEndStream()
    }
}
```

## 关键注意事项

1. 音频格式: 16kHz, 单声道, 16-bit PCM
2. Chunk 大小: 每 100ms 约 3200 bytes
3. Base64 编码: 使用 `Base64.NO_WRAP`
4. 顺序: `start_stream` → 等待 `stream_ready` → 发送音频 → `end_stream`

