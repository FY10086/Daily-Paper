# 定时执行说明

推荐先在本机用 `cron` 每天固定时间运行一次。

## 示例

每天上午 08:00 执行（先确认 `python3` 路径）：

```cron
0 8 * * * cd /home/tang/task/Daily_Paper && /usr/bin/python3 daily_run.py >> /home/tang/task/Daily_Paper/logs/daily_run.log 2>&1
```

## 配置步骤

1. 执行 `crontab -e`
2. 写入上述任务（按需调整时间）
3. 确保 SMTP 环境变量在 cron 环境可读取（可写在脚本中或 crontab 前置导出）

