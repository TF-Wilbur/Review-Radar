"""AppPulse - 感知每一条用户心声"""

import logging

__version__ = "0.1.0"

# 配置项目级 logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("review_radar")
