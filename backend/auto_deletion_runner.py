import asyncio
import os
from dotenv import load_dotenv
from job_management.auto_deletion import AutoDeletionManager
from job_management.job_manager import JobManager

load_dotenv()

async def main():
    max_concurrent = int(os.getenv("MAX_CONCURRENT_REQUESTS", "2000"))
    webhook_url = os.getenv("WEBHOOK_URL", "")
    auto_delete_delay = int(os.getenv("AUTO_DELETE_DELAY", "240"))
    manager = JobManager(max_concurrent, webhook_url)
    auto_deletion = AutoDeletionManager(auto_delete_delay, webhook_url, manager.jobs)
    print(f"Starting auto-deletion service with {auto_delete_delay} second delay...")
    await auto_deletion.cleanup_old_jobs()

if __name__ == "__main__":
    asyncio.run(main())
