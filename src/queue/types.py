# ruflo-kb/src/queue/types.py
# Task queue type definitions
from enum import Enum

class QueueStatus(str, Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    PAUSED = "paused"
