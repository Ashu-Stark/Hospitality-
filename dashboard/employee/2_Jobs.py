from lib import employee_ctx, tenancy, ui, worker_ui

ui.setup("employee/2_Jobs.py", "Jobs", employee=True)
ctx = employee_ctx.context()
employee_ctx.header(ctx, "Jobs")
worker_ui.phone(ctx["me"], ctx["dept"], ctx["shift"], int(tenancy.active_settings().get("offer_seconds", 30)), allow_upload=False)
worker_ui.completed(ctx["me"])
ui.footer()
