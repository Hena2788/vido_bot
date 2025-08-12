import os
import logging
import time
import threading
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from flask import Flask
import yt_dlp
from pathlib import Path

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)
MAX_RETRIES = 2
REQUEST_DELAY = 1.5  # seconds

# Flask app for health checks
app = Flask(__name__)

@app.route('/healthz')
def health_check():
    """Endpoint for Render health checks"""
    return "OK", 200

def run_flask_app():
    """Run Flask in a separate thread"""
    app.run(host='0.0.0.0', port=5000)

async def send_video(update: Update, video_path: Path, caption=""):
    """Enhanced video sending with better error handling"""
    try:
        if not video_path.exists():
            raise FileNotFoundError("Video file not found")
            
        file_size = video_path.stat().st_size / (1024 * 1024)  # in MB
        if file_size > 50:
            await update.message.reply_text("❌ Video is too large (max 50MB)")
            return False

        with open(video_path, 'rb') as video:
            await update.message.reply_video(
                video=video,
                caption=caption,
                supports_streaming=True,
                read_timeout=60,
                write_timeout=60
            )
        return True
    except Exception as e:
        logger.error(f"Send video failed: {type(e).__name__}: {str(e)}")
        await update.message.reply_text("❌ Failed to send video. Please try again.")
        return False
    finally:
        try:
            video_path.unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Failed to delete video file: {str(e)}")

def download_with_ytdlp(url, output_path, retry=0):
    """Improved download function with retry logic"""
    ydl_opts = {
        'outtmpl': str(output_path.with_suffix('.%(ext)s')),
        'quiet': True,
        'no_warnings': True,
        'format': 'best[filesize<50M]',
        'merge_output_format': 'mp4',
        'retries': 3,
        'socket_timeout': 30,
        'extractor_args': {
            'instagram': {'skip': ['hls', 'dash']},
            'youtube': {'skip': ['dash', 'hls']},
            'tiktok': {'skip': ['dash', 'hls']}
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = Path(ydl.prepare_filename(info))
            
            if downloaded_file.suffix != '.mp4':
                new_path = downloaded_file.with_suffix('.mp4')
                downloaded_file.rename(new_path)
                return new_path
            return downloaded_file
            
    except yt_dlp.utils.DownloadError as e:
        if retry < MAX_RETRIES:
            logger.warning(f"Retry {retry + 1} for {url}")
            time.sleep(2)
            return download_with_ytdlp(url, output_path, retry + 1)
        logger.error(f"Download failed after {MAX_RETRIES} retries: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected download error: {type(e).__name__}: {str(e)}")
        return None

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Improved link handler with better feedback"""
    url = update.message.text.strip()
    time.sleep(REQUEST_DELAY)
    
    if "instagram.com" in url:
        platform = "Instagram"
        await update.message.reply_text("📥 Downloading Instagram video...")
        video_path = download_with_ytdlp(url, DOWNLOADS_DIR / "ig_video")
    elif "tiktok.com" in url:
        platform = "TikTok"
        await update.message.reply_text("📥 Downloading TikTok video...")
        video_path = download_with_ytdlp(url, DOWNLOADS_DIR / "tt_video")
    elif "youtube.com" in url or "youtu.be" in url:
        platform = "YouTube"
        await update.message.reply_text("📥 Downloading YouTube video...")
        video_path = download_with_ytdlp(url, DOWNLOADS_DIR / "yt_video")
    else:
        await update.message.reply_text("🔗 Please send a valid Instagram, TikTok, or YouTube link.")
        return

    if video_path and video_path.exists():
        await send_video(update, video_path, f"🎥 {platform} Video")
    else:
        await update.message.reply_text(
            "❌ Failed to download video.\n"
            "Possible reasons:\n"
            "- Link is private/restricted\n"
            "- Server is busy (try again later)\n"
            "- Video format not supported"
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enhanced welcome message"""
    await update.message.reply_text(
        "👋 Welcome to Video Downloader Bot!\n\n"
        "📤 Supported platforms:\n"
        "- Instagram Reels/Posts\n"
        "- TikTok Videos\n"
        "- YouTube Videos/Shorts\n\n"
        "⚠️ Note: Private/restricted content cannot be downloaded"
    )

def main():
    if not TOKEN:
        raise ValueError("Bot token not found. Check your .env file.")

    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()

    # Start Telegram bot
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    logger.info("🚀 Bot is running with health check at http://0.0.0.0:5000/healthz")
    app.run_polling()

if __name__ == '__main__':
    main()