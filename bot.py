"""NoneBot CLI entry point.

``nb run`` looks for this file before it falls back to its generated bootstrap
script. Delegating to ``run.main`` ensures flat QQ environment variables are
materialized before ``nonebot.init()``.
"""

from run import main


if __name__ == "__main__":
    main()
