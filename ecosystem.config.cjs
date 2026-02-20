module.exports = {
  apps: [
    {
      name: "warp2api-gateway",
      script: "uv",
      cwd: "./",
      interpreter: "none",
      args: "run warp2api-gateway",
      watch: ["src", "static"],
      ignore_watch: [".git", ".venv", "logs", "__pycache__", "*.log"],
      watch_delay: 1200,
      autorestart: true,
      max_restarts: 50,
      min_uptime: "5s",
      out_file: "logs/pm2_warp_gateway_out.log",
      error_file: "logs/pm2_warp_gateway_err.log",
      merge_logs: true,
      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
