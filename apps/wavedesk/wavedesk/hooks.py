app_name = "wavedesk"
app_title = "WaveDesk"
app_publisher = "WaveDesk"
app_description = "Multi-tenant WhatsApp team-inbox & group-management SaaS"
app_email = "bacokushal@gmail.com"
app_license = "Proprietary"

# Seeding is idempotent — safe on every migrate (plans + AI pricing config).
after_install = "wavedesk.setup.install.after_install"
after_migrate = ["wavedesk.setup.install.seed_defaults"]

# Tenancy hooks (permission_query_conditions / has_permission for ALL WD DocTypes)
# are registered here in Session 0.3 from wavedesk/tenancy.py — single registration point.
