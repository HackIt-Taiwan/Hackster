"""
Moderation queue service for handling content moderation tasks.
"""
import asyncio
import logging
import time
import uuid
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task status enumeration."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ModerationTask:
    """Data class for moderation tasks."""
    id: str
    task_func: Callable
    task_data: Dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    retries: int = 0
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()


class ModerationQueue:
    """
    Queue for handling content moderation tasks asynchronously.
    
    This class manages a queue of moderation tasks and processes them
    with configurable concurrency and retry logic.
    """
    
    def __init__(self, 
                 max_concurrent: int = 3,
                 check_interval: float = 1.0,
                 retry_interval: float = 5.0,
                 max_retries: int = 5):
        """
        Initialize the moderation queue.
        
        Args:
            max_concurrent: Maximum number of concurrent tasks
            check_interval: Interval between queue checks in seconds
            retry_interval: Interval before retrying failed tasks in seconds
            max_retries: Maximum number of retry attempts
        """
        self.max_concurrent = max_concurrent
        self.check_interval = check_interval
        self.retry_interval = retry_interval
        self.max_retries = max_retries
        
        self.queue: List[ModerationTask] = []
        self.processing_tasks: Dict[str, ModerationTask] = {}
        self.completed_tasks: Dict[str, ModerationTask] = {}
        self.failed_tasks: Dict[str, ModerationTask] = {}
        
        self.running = False
        self.queue_task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()
        
        self.logger = logging.getLogger(__name__)
        
    async def start(self):
        """Start the queue processor."""
        if self.running:
            return
            
        self.running = True
        self.queue_task = asyncio.create_task(self._process_queue())
        self.logger.info("Moderation queue started")
        
    def add_moderation_task(self, task_func: Callable, task_data: Dict[str, Any], task_id: Optional[str] = None):
        """
        Add a moderation task to the queue.
        
        Args:
            task_func: The function to execute for moderation
            task_data: Data to pass to the task function
            task_id: Optional task ID, will be generated if not provided
        """
        if not self.running:
            self.logger.warning("Queue is not running, task will not be processed")
            return
            
        task_id = task_id or str(uuid.uuid4())
        
        task = ModerationTask(
            id=task_id,
            task_func=task_func,
            task_data=task_data
        )
        
        self.queue.append(task)
        self.logger.info(f"Added moderation task to queue: {task_id}")
        
        # Log queue status for monitoring
        active_count = len(self.processing_tasks)
        pending_count = len(self.queue)
        self.logger.info(f"Queue status: {pending_count} pending, {active_count} processing")
        
    async def _process_queue(self):
        """Main queue processing loop."""
        self.logger.info("Starting moderation queue processor")
        
        while self.running:
            try:
                async with self.lock:
                    # Check if we can start new tasks
                    available_slots = self.max_concurrent - len(self.processing_tasks)
                    
                    if available_slots > 0 and self.queue:
                        # Start new tasks up to the available slots
                        tasks_to_start = min(available_slots, len(self.queue))
                        
                        for _ in range(tasks_to_start):
                            task = self.queue.pop(0)
                            task.status = TaskStatus.PROCESSING
                            task.started_at = time.time()
                            self.processing_tasks[task.id] = task
                            
                            # Start the task
                            asyncio.create_task(self._execute_task(task))
                            
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                self.logger.error(f"Error in queue processing loop: {e}")
                await asyncio.sleep(self.check_interval)
                
    async def _execute_task(self, task: ModerationTask):
        """Execute a single moderation task."""
        try:
            self.logger.info(f"Executing moderation task: {task.id}")
            
            # Execute the task function
            await task.task_func(**task.task_data)
            
            # Mark task as completed
            async with self.lock:
                task.status = TaskStatus.COMPLETED
                task.completed_at = time.time()
                self.completed_tasks[task.id] = task
                if task.id in self.processing_tasks:
                    del self.processing_tasks[task.id]
                    
            self.logger.info(f"Moderation task completed successfully: {task.id}")
            
        except Exception as e:
            self.logger.error(f"Error executing moderation task {task.id}: {e}")
            
            async with self.lock:
                task.retries += 1
                task.error = str(e)
                
                if task.retries < self.max_retries:
                    # Retry the task
                    task.status = TaskStatus.PENDING
                    self.queue.append(task)
                    self.logger.info(f"Retrying moderation task {task.id} (attempt {task.retries + 1}/{self.max_retries})")
                else:
                    # Max retries exceeded, mark as failed
                    task.status = TaskStatus.FAILED
                    self.failed_tasks[task.id] = task
                    self.logger.error(f"Moderation task failed after {self.max_retries} attempts: {task.id}")
                
                # Remove from processing tasks
                if task.id in self.processing_tasks:
                    del self.processing_tasks[task.id]
                    
    def get_queue_status(self):
        """Get current queue status."""
        return {
            "pending": len(self.queue),
            "processing": len(self.processing_tasks),
            "completed": len(self.completed_tasks),
            "failed": len(self.failed_tasks),
            "running": self.running
        }
        
    def stop(self):
        """Stop the queue processor."""
        self.running = False
        if self.queue_task:
            self.queue_task.cancel()
        self.logger.info("Moderation queue stopped")


# Global moderation queue instance
moderation_queue: Optional[ModerationQueue] = None


async def start_moderation_queue(config):
    """Start the global moderation queue."""
    global moderation_queue
    
    if not config.moderation.queue_enabled:
        logger.info("Moderation queue is disabled")
        return
        
    moderation_queue = ModerationQueue(
        max_concurrent=config.moderation.queue_max_concurrent,
        check_interval=config.moderation.queue_check_interval,
        retry_interval=config.moderation.queue_retry_interval,
        max_retries=config.moderation.queue_max_retries
    )
    
    await moderation_queue.start()
    logger.info("Global moderation queue started")


def get_moderation_queue() -> Optional[ModerationQueue]:
    """Get the global moderation queue instance."""
    return moderation_queue 