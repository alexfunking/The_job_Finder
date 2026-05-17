import sys
import main

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("Starting custom test run...")
try:
    print("Running job hunt cycle...")
    main.frequent_job_hunt_cycle()
    print("Running daily summary...")
    main.send_daily_summary()
except Exception as e:
    print(f"Exception caught: {e}")
print("Test run completed.")
