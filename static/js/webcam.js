class DigiMarkCamera {
  constructor(videoId, canvasId) {
    this.video = document.getElementById(videoId);
    this.canvas = document.getElementById(canvasId);
    this.stream = null;
  }

  async start() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      throw new Error("Camera API is not supported in this browser.");
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      this.video.srcObject = this.stream;
      await this.video.play();
    } catch (error) {
      throw new Error("Camera permission denied or camera unavailable.");
    }
  }

  stop() {
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }
  }

  captureFrameBase64() {
    if (!this.video.videoWidth || !this.video.videoHeight) {
      throw new Error("Camera frame is not ready yet.");
    }
    this.canvas.width = this.video.videoWidth;
    this.canvas.height = this.video.videoHeight;
    const ctx = this.canvas.getContext("2d");
    ctx.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);
    return this.canvas.toDataURL("image/jpeg", 0.9);
  }

  async autoCaptureFrames(totalFrames = 5, intervalMs = 1000, onProgress = null) {
    const frames = [];
    for (let i = 0; i < totalFrames; i += 1) {
      if (i > 0) {
        await new Promise((resolve) => setTimeout(resolve, intervalMs));
      }
      frames.push(this.captureFrameBase64());
      if (onProgress) {
        onProgress(i + 1, totalFrames);
      }
    }
    return frames;
  }
}

window.DigiMarkCamera = DigiMarkCamera;
