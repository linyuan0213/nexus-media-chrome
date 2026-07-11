# Nexus Media Chrome Service — task runner
# https://github.com/casey/just

# 显示帮助（默认）
default:
    @just --list

# 安装项目依赖
install:
    uv sync

# 安装开发依赖
dev:
    uv sync --dev

# 运行测试 [args: pytest 参数]
test *args:
    uv run pytest tests/ -v {{args}}

# 运行测试并生成覆盖率报告
test-cov:
    uv run pytest tests/ -v --cov=src --cov-report=term-missing

# 运行 ruff 代码检查
lint:
    uv run ruff check .

# 运行 pyright 类型检查
typecheck:
    uv run pyright src/ tests/

# 运行 lint + typecheck + test
check: lint typecheck test

# 启动开发服务器
run:
    uv run python main.py

# 清理缓存文件
clean:
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name '*.pyc' -delete 2>/dev/null || true
