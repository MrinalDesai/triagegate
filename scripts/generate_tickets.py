"""
Generate synthetic labeled bug-report tickets for training and evaluation.

Outputs:
    data/tickets.csv          – 200 tickets, 40 per domain, seed=42
    data/eval_tickets.csv     –  50 tickets, 10 per domain, seed=99
    data/incident_history.csv – resolution records for ALL tickets (same ids)

Incident history schema
-----------------------
id            : matches tickets.csv / eval_tickets.csv
files_changed : 1-2 plausible file paths derived from the domain
risk_level    : "high" when files_changed touches a payment/auth/session-like
                path, "low" otherwise.

                Risk mapping (explicit):
                  HIGH paths contain any of the keywords:
                    payment, auth, session, login, checkout, billing
                  LOW  paths contain only neutral keywords (e.g. orders, db,
                    views, components, routes, pipeline)

impact        : one generated sentence describing the production impact
tests_after   : always "all passed"
verdict       : always "fix_verified"

Usage:
    python scripts/generate_tickets.py
"""

from __future__ import annotations

import csv
import os
import random
from pathlib import Path

# ---------------------------------------------------------------------------
# Vocabulary lists – shared slot-fill material
# ---------------------------------------------------------------------------

SERVICES = [
    "user-service", "order-service", "payment-service", "auth-service",
    "notification-service", "inventory-service", "search-service",
    "billing-service", "reporting-service", "gateway",
]

ERROR_CODES = ["500", "502", "503", "504", "400", "401", "403", "404", "422", "429"]

HTTP_METHODS = ["POST", "GET", "PUT", "PATCH", "DELETE"]

ENDPOINTS = [
    "/orders", "/users", "/payments", "/login", "/logout", "/refresh",
    "/products", "/checkout", "/invoices", "/reports", "/sessions",
    "/webhooks", "/profile", "/search",
]

COMPONENTS = [
    "LoginForm", "CheckoutButton", "NavBar", "UserDashboard", "OrderTable",
    "PaymentModal", "SearchBar", "ProfilePage", "CartWidget", "ReportChart",
]

DB_TABLES = [
    "users", "orders", "sessions", "transactions", "products",
    "audit_logs", "payments", "inventory", "events", "notifications",
]

DB_OPS = ["SELECT", "INSERT", "UPDATE", "DELETE", "JOIN"]

BROWSERS = ["Chrome", "Firefox", "Safari", "Edge"]

ENVS = ["staging", "production", "dev", "QA"]

BUILD_TOOLS = ["Docker", "webpack", "Gradle", "Maven", "npm", "pip", "cargo", "make"]

CI_TOOLS = ["GitHub Actions", "Jenkins", "CircleCI", "GitLab CI", "Buildkite"]

AUTH_METHODS = ["JWT", "OAuth", "SSO", "2FA", "session cookie", "API key", "SAML"]

TOKEN_ISSUES = [
    "expires immediately", "is rejected with 401", "is not refreshed",
    "has an incorrect signature", "is missing from the response",
]

SYMPTOMS = [
    "after deploy", "after a config change", "since last release",
    "after the migration", "intermittently", "under high load",
    "on every request", "only in production",
]

# ---------------------------------------------------------------------------
# Template definitions – 10-12 per domain
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, list[tuple[str, str]]] = {

    # ---- API ---------------------------------------------------------------
    "api": [
        (
            "{method} {endpoint} returns {code} {symptom}",
            "The {service} endpoint {method} {endpoint} started returning HTTP {code} {symptom}. "
            "Logs show an unhandled exception in the request handler. "
            "Rolling back the last deployment temporarily fixes it.",
        ),
        (
            "{service} API throws {code} on {method} {endpoint}",
            "Calling {method} {endpoint} on {service} consistently results in a {code} error. "
            "The request payload is valid according to the schema. "
            "The issue appeared {symptom}.",
        ),
        (
            "{method} {endpoint} returns empty response body",
            "The {service} handler for {method} {endpoint} returns a {code} status with an empty body. "
            "This breaks downstream consumers that expect a JSON object. "
            "Reproduces reliably in {env}.",
        ),
        (
            "API rate limit not enforced on {endpoint}",
            "The {service} route {endpoint} does not respect the 429 throttle limit. "
            "Clients can flood it without being blocked {symptom}. "
            "The rate-limit middleware appears to be bypassed.",
        ),
        (
            "{service} response times spike to 30 s on {method} {endpoint}",
            "{method} {endpoint} in {service} takes over 30 seconds to respond {symptom}. "
            "Tracing shows the bottleneck is inside the request serialisation layer. "
            "Other routes are unaffected.",
        ),
        (
            "{endpoint} returns 404 after route refactor in {service}",
            "After a route rename in {service} the path {endpoint} returns {code}. "
            "Existing API clients are broken. "
            "No redirect is configured for the old path.",
        ),
        (
            "{service} returns wrong Content-Type on {method} {endpoint}",
            "{method} {endpoint} sends back text/html instead of application/json {symptom}. "
            "This causes JSON parse failures in the frontend. "
            "The accept header is being ignored.",
        ),
        (
            "Pagination broken on {endpoint} – always returns first page",
            "The {service} paginated endpoint {endpoint} ignores the page parameter {symptom}. "
            "Every {method} request returns the first 20 records regardless of offset. "
            "Integration tests were not catching this regression.",
        ),
        (
            "{service} endpoint {endpoint} leaks stack trace in {code} response",
            "{method} {endpoint} on {service} returns a {code} with a full stack trace in the body. "
            "This exposes internal paths and library versions. "
            "Error handling middleware is not sanitising the output.",
        ),
        (
            "CORS headers missing on {service} {method} {endpoint}",
            "Cross-origin requests to {method} {endpoint} on {service} fail with a CORS error {symptom}. "
            "The Access-Control-Allow-Origin header is absent. "
            "Reverting last nginx config change resolves it.",
        ),
        (
            "the API is broken on {endpoint} – getting {code} every time",
            "{service} keeps throwing {code} when you hit {endpoint} {symptom}. "
            "Nothing in the logs explains why. "
            "Started after the last hotfix was pushed.",
        ),
        (
            "{service} times out calling {endpoint} under load",
            "Under load testing {service} cannot finish {method} {endpoint} within the 5-second SLA. "
            "Connection pool exhaustion is suspected {symptom}. "
            "The issue is not reproduced locally.",
        ),
    ],

    # ---- DATABASE ----------------------------------------------------------
    "database": [
        (
            "Slow {op} query on {table} table causing timeouts",
            "A {op} on the {table} table is running a full sequential scan {symptom}. "
            "Query time exceeds 10 seconds and connection pool slots are exhausted. "
            "Adding an index on the foreign key should fix it.",
        ),
        (
            "Deadlock detected on {table} during concurrent {op}",
            "Two concurrent {op} transactions on {table} are deadlocking {symptom}. "
            "The database error log shows lock-wait timeouts. "
            "Row-level locking order needs to be standardised.",
        ),
        (
            "Migration script drops wrong index on {table}",
            "The latest migration accidentally removes a covering index on {table}. "
            "Subsequent {op} queries degrade significantly {symptom}. "
            "The migration must be rolled back and rewritten.",
        ),
        (
            "Connection pool exhausted – all {table} queries failing",
            "The connection pool limit is reached and all queries against {table} are rejected {symptom}. "
            "Idle connections are not being released after {op} operations. "
            "Pool size needs to be increased or connections need to be closed properly.",
        ),
        (
            "Duplicate rows inserted into {table} due to missing constraint",
            "Concurrent {op} operations on {table} insert duplicate records {symptom}. "
            "There is no unique constraint on the business key column. "
            "A unique index and application-level guard are both needed.",
        ),
        (
            "{op} on {table} fails with foreign key constraint violation",
            "Attempting a {op} on {table} returns a foreign key constraint error {symptom}. "
            "The referenced row in the parent table was deleted out of order. "
            "Cascade rules need to be reviewed.",
        ),
        (
            "Database replication lag spikes to 60 s on {table} writes",
            "Heavy {op} traffic on {table} causes replication lag to exceed 60 seconds {symptom}. "
            "Read replicas are serving stale data. "
            "Write batching or replica promotion is needed as a short-term fix.",
        ),
        (
            "NULL values returned for non-nullable column in {table}",
            "A recent {op} migration set NULL for a previously non-nullable column in {table} {symptom}. "
            "Application code does not handle None and throws an exception. "
            "A data-repair script is needed.",
        ),
        (
            "Query planner chooses bad plan for JOIN on {table}",
            "The query optimiser picks a nested-loop join on {table} instead of a hash join {symptom}. "
            "Running ANALYZE resolves it temporarily. "
            "Auto-vacuum statistics are out of date.",
        ),
        (
            "database is super slow – {table} {op} taking forever",
            "Every {op} hitting {table} is taking way too long {symptom}. "
            "The whole app slows down and users are complaining. "
            "Probably missing an index again.",
        ),
        (
            "Schema mismatch after migration breaks {op} on {table}",
            "Column type was changed in the migration but ORM models were not updated for {table}. "
            "{op} queries now fail with a type-cast error {symptom}. "
            "Both the migration and the model must be aligned.",
        ),
    ],

    # ---- FRONTEND ----------------------------------------------------------
    "frontend": [
        (
            "{component} fails to render after CSS update",
            "The {component} component loses its styles after the latest CSS refactor {symptom}. "
            "The browser console shows a missing class name. "
            "Reverting the stylesheet change restores the layout.",
        ),
        (
            "page looks weird on mobile – {component} overflows viewport",
            "{component} overflows the screen width on mobile {symptom}. "
            "The responsive breakpoint media query is not applied correctly. "
            "Tested on {browser} and the issue is consistent.",
        ),
        (
            "{component} shows blank screen on {browser}",
            "{component} renders a blank white screen in {browser} {symptom}. "
            "Other browsers display it correctly. "
            "A vendor-prefixed CSS property may be unsupported.",
        ),
        (
            "Infinite scroll breaks on {component} after state update",
            "Scrolling past the first page in {component} no longer loads more items {symptom}. "
            "The pagination state is reset on each render. "
            "The useEffect dependency array is likely incorrect.",
        ),
        (
            "{component} button click triggers double submission",
            "Clicking the submit button on {component} sends the form twice {symptom}. "
            "No debounce or disabled state is applied after the first click. "
            "Users end up with duplicate records.",
        ),
        (
            "the app is broken after login – {component} not loading",
            "After a successful login {component} just spins and never loads {symptom}. "
            "The network tab shows the data fetch succeeds but the component doesn't render. "
            "Probably a state management bug introduced recently.",
        ),
        (
            "{component} layout broken in {browser} after dependency upgrade",
            "Upgrading the UI library broke the layout of {component} in {browser} {symptom}. "
            "Flexbox container widths are calculated incorrectly. "
            "Pinning the previous library version is a workaround.",
        ),
        (
            "Tooltip on {component} flickers and disappears immediately",
            "The tooltip attached to {component} appears for a split second then hides {symptom}. "
            "Mouse-leave fires prematurely on the tooltip wrapper. "
            "A pointer-events CSS fix may be needed.",
        ),
        (
            "{component} does not update when props change",
            "{component} displays stale data even when the parent passes new props {symptom}. "
            "Component is not re-rendering because of a memoisation issue. "
            "Removing React.memo resolves it temporarily.",
        ),
        (
            "Dark mode toggle breaks {component} colour scheme",
            "Switching to dark mode leaves {component} with hardcoded light colours {symptom}. "
            "CSS variables for the theme are not applied to this component. "
            "A theming audit is needed.",
        ),
        (
            "Keyboard navigation skips {component} – accessibility issue",
            "Tab-key navigation bypasses the interactive elements inside {component} {symptom}. "
            "The tabIndex attributes are missing. "
            "Screen-reader users cannot reach the control.",
        ),
    ],

    # ---- AUTH --------------------------------------------------------------
    "auth": [
        (
            "{auth_method} token {token_issue} on login",
            "After authenticating with {auth_method} the token {token_issue}. "
            "Users are immediately redirected back to the login page {symptom}. "
            "Token issuer configuration may have changed.",
        ),
        (
            "Login session expires immediately after refresh",
            "The session cookie is invalidated as soon as the user refreshes the page {symptom}. "
            "The {auth_method} expiry is set to zero seconds in the {env} config. "
            "Session TTL needs to be corrected.",
        ),
        (
            "{auth_method} sign-in returns 401 – credentials are correct",
            "Valid credentials are rejected by the {auth_method} provider with a 401 {symptom}. "
            "The shared secret was rotated but the {service} was not updated. "
            "Redeploying with the new secret fixes it.",
        ),
        (
            "Password reset email not sent from {service}",
            "The {service} password reset flow does not dispatch the email {symptom}. "
            "The SMTP relay credentials in {env} have expired. "
            "Users are locked out of their accounts.",
        ),
        (
            "{auth_method} callback URL mismatch causes redirect failure",
            "The OAuth callback URL registered in the provider does not match {service} {symptom}. "
            "Users see an 'invalid_redirect_uri' error after authorising. "
            "The URL list in the OAuth application settings must be updated.",
        ),
        (
            "2FA code always rejected on {service} – clock drift suspected",
            "TOTP codes for 2FA are consistently rejected on {service} {symptom}. "
            "The server and client clocks differ by more than 30 seconds. "
            "NTP synchronisation on the server is needed.",
        ),
        (
            "Logout does not invalidate {auth_method} token on {service}",
            "Calling the logout endpoint on {service} does not revoke the {auth_method} token {symptom}. "
            "The token remains valid until natural expiry. "
            "Server-side token blacklisting must be implemented.",
        ),
        (
            "Role permission check bypassed in {service} – users see admin pages",
            "Non-admin users can access the admin panel on {service} {symptom}. "
            "The middleware that checks role claims was removed during a refactor. "
            "Authorisation middleware must be reinstated.",
        ),
        (
            "{auth_method} refresh token rotation broken on {service}",
            "Refresh token rotation in {service} issues a new token but also invalidates valid sessions {symptom}. "
            "Concurrent requests race on the refresh endpoint. "
            "A mutex or atomic token swap is required.",
        ),
        (
            "can't log in – {service} keeps saying invalid {auth_method}",
            "Users can't get past the login screen on {service} {symptom}. "
            "The error message says the {auth_method} is invalid even though it's correct. "
            "Something changed in the auth config and nobody documented it.",
        ),
        (
            "Account lockout not triggered after failed {auth_method} attempts",
            "Brute-force attempts against {auth_method} on {service} are not triggering lockout {symptom}. "
            "The failed-attempt counter is stored in a cache that was recently cleared. "
            "Persistent counter storage is needed.",
        ),
    ],

    # ---- BUILD -------------------------------------------------------------
    "build": [
        (
            "{build_tool} build fails on dependency resolution {symptom}",
            "The {build_tool} build cannot resolve a transitive dependency {symptom}. "
            "The package registry returns a 404 for the pinned version. "
            "Unpinning or mirroring the dependency is needed.",
        ),
        (
            "{ci_tool} pipeline fails at {build_tool} step",
            "The {ci_tool} workflow errors out during the {build_tool} step {symptom}. "
            "Build logs show a missing environment variable. "
            "The secret was removed from the CI environment without notice.",
        ),
        (
            "Docker image fails to build – layer cache invalidated",
            "The Docker image build fails because the layer cache is stale {symptom}. "
            "A base image digest changed and {build_tool} reinstalls everything from scratch. "
            "Pinning the base image tag resolves it.",
        ),
        (
            "{build_tool} test step exits with code 137 in {ci_tool}",
            "The {build_tool} test job is killed with OOM (exit 137) in {ci_tool} {symptom}. "
            "The runner has insufficient memory for the full test suite. "
            "Parallelising tests or upgrading the runner tier is needed.",
        ),
        (
            "Lint check fails on every PR after {build_tool} upgrade",
            "Upgrading {build_tool} introduced new linting rules that fail on existing code {symptom}. "
            "Over 200 files have style violations. "
            "Auto-fix should be run and the config should be updated.",
        ),
        (
            "{ci_tool} deployment fails – artifact not found after {build_tool} build",
            "The deployment step in {ci_tool} cannot locate the artifact produced by {build_tool} {symptom}. "
            "The output directory path changed in the new {build_tool} version. "
            "CI config must reference the correct output path.",
        ),
        (
            "Build time tripled since adding {build_tool} to {ci_tool}",
            "Build duration jumped from 4 minutes to 14 minutes after integrating {build_tool} into {ci_tool} {symptom}. "
            "Caching is not configured for the new step. "
            "Enabling dependency caching cuts the time back to baseline.",
        ),
        (
            "{build_tool} fails with permission denied on {ci_tool} runner",
            "The {build_tool} step writes to a directory the {ci_tool} runner user cannot access {symptom}. "
            "Runner runs as a non-root user without write permission. "
            "Either the directory permissions or the runner user must be fixed.",
        ),
        (
            "Broken build – {build_tool} can't find config file in {ci_tool}",
            "{build_tool} exits immediately because the config file is missing from the {ci_tool} workspace {symptom}. "
            "The file was gitignored but is required for the build. "
            "It should be added to the repo or generated during CI setup.",
        ),
        (
            "nothing builds anymore – {build_tool} keeps crashing",
            "Every time {build_tool} runs it just crashes {symptom}. "
            "No useful error message, just a non-zero exit code. "
            "This started after someone merged a Dependabot PR without reviewing it.",
        ),
        (
            "{ci_tool} stages run out of order – {build_tool} step skipped",
            "A misconfigured {ci_tool} pipeline runs stages out of order so the {build_tool} step is skipped {symptom}. "
            "The artifact is never produced. "
            "Stage dependency declarations need to be fixed.",
        ),
    ],
}

# ---------------------------------------------------------------------------
# Slot-fill helper
# ---------------------------------------------------------------------------

DOMAIN_SLOTS: dict[str, dict[str, list[str]]] = {
    "api":      {"service": SERVICES, "method": HTTP_METHODS, "endpoint": ENDPOINTS,
                 "code": ERROR_CODES, "symptom": SYMPTOMS, "env": ENVS},
    "database": {"op": DB_OPS, "table": DB_TABLES, "symptom": SYMPTOMS},
    "frontend": {"component": COMPONENTS, "browser": BROWSERS, "symptom": SYMPTOMS},
    "auth":     {"auth_method": AUTH_METHODS, "token_issue": TOKEN_ISSUES,
                 "service": SERVICES, "symptom": SYMPTOMS, "env": ENVS},
    "build":    {"build_tool": BUILD_TOOLS, "ci_tool": CI_TOOLS, "symptom": SYMPTOMS},
}


def _fill(template: str, slots: dict[str, list[str]], rng: random.Random) -> str:
    """Replace each {slot} in template with a random choice from the slot list."""
    result = template
    for key, choices in slots.items():
        placeholder = "{" + key + "}"
        while placeholder in result:
            result = result.replace(placeholder, rng.choice(choices), 1)
    return result


# ---------------------------------------------------------------------------
# Incident history generation
# ---------------------------------------------------------------------------

# File-path candidates per domain.
# Each entry is a tuple: (file_path, is_high_risk).
#
# Risk mapping (authoritative):
#   HIGH risk paths contain any of the following substrings:
#       payment, auth, session, login, checkout, billing
#   LOW  risk paths do NOT contain any of those substrings.
#
# This mapping is applied verbatim in generate_incident_history() below.

_HIGH_RISK_KEYWORDS = {"payment", "auth", "session", "login", "checkout", "billing"}

_DOMAIN_FILE_CANDIDATES: dict[str, list[tuple[str, str]]] = {
    # (file_path, risk_label)
    "api": [
        ("app/orders.py",    "low"),
        ("app/payments.py",  "high"),   # payment → high
        ("app/invoices.py",  "low"),
        ("app/webhooks.py",  "low"),
        ("app/routes.py",    "low"),
        ("app/checkout.py",  "high"),   # checkout → high
    ],
    "database": [
        ("app/db.py",         "low"),
        ("app/models.py",     "low"),
        ("app/migrations.py", "low"),
        ("app/billing.py",    "high"),  # billing → high
        ("app/queries.py",    "low"),
    ],
    "frontend": [
        ("app/views/login.py",    "high"),  # login → high
        ("app/views/checkout.py", "high"),  # checkout → high
        ("app/views/orders.py",   "low"),
        ("app/components.py",     "low"),
        ("app/ui/dashboard.py",   "low"),
    ],
    "auth": [
        ("app/sessions.py",     "high"),  # session → high
        ("app/auth.py",         "high"),  # auth → high
        ("app/login.py",        "high"),  # login → high
        ("app/auth_tokens.py",  "high"),  # auth → high
        ("app/permissions.py",  "low"),
    ],
    "build": [
        ("ci/pipeline.py",     "low"),
        ("ci/docker.py",       "low"),
        ("ci/deploy.py",       "low"),
        ("scripts/build.py",   "low"),
        ("scripts/release.py", "low"),
    ],
}

# Impact sentence templates per domain.
_IMPACT_TEMPLATES: dict[str, list[str]] = {
    "api": [
        "API errors caused {n} downstream requests to fail per hour.",
        "{n} customers received empty responses from the {svc} endpoint.",
        "Rate-limit bypass allowed {n} uncapped requests per minute.",
        "Stale API responses served to {n} active sessions.",
    ],
    "database": [
        "Duplicate charges recorded for {n} customers due to missing constraint.",
        "Query timeouts blocked {n} database write operations per minute.",
        "Replication lag caused stale reads affecting {n} concurrent users.",
        "Missing index caused {n} sequential scans per hour in production.",
    ],
    "frontend": [
        "Broken UI prevented {n} users from completing checkout.",
        "Blank screen on {browser} locked out {n} mobile users.",
        "Double-submission bug created {n} duplicate orders.",
        "Accessibility regression blocked keyboard navigation for {n} users.",
    ],
    "auth": [
        "Session invalidation logged out {n} active users unexpectedly.",
        "Auth bypass exposed admin panel to {n} non-privileged accounts.",
        "Stale sessions persisted on mobile for {n} users after logout.",
        "Token rotation bug caused {n} failed refresh attempts per hour.",
    ],
    "build": [
        "Failed CI pipeline blocked {n} pull requests from merging.",
        "Broken artifact prevented {n} deployments to production.",
        "OOM in test runner caused {n} flaky test suite runs.",
        "Mis-ordered pipeline stages skipped tests on {n} branches.",
    ],
}


def _compute_risk(files: list[str]) -> str:
    """Return 'high' if any file path contains a high-risk keyword, else 'low'.

    High-risk keywords: payment, auth, session, login, checkout, billing.
    This function is the single authoritative implementation of the risk
    mapping described in the module docstring.
    """
    for path in files:
        path_lower = path.lower()
        for keyword in _HIGH_RISK_KEYWORDS:
            if keyword in path_lower:
                return "high"
    return "low"


def _generate_incident_row(
    ticket_id: str,
    domain: str,
    rng: random.Random,
) -> dict:
    """Generate a single incident-history record for *ticket_id*."""
    candidates = _DOMAIN_FILE_CANDIDATES[domain]

    # Pick 1-2 distinct file paths, weighted so we occasionally get 2.
    n_files = rng.choice([1, 1, 2])  # ~33 % chance of 2 files
    chosen = rng.sample(candidates, min(n_files, len(candidates)))
    files = [c[0] for c in chosen]
    files_changed = ", ".join(files)

    risk_level = _compute_risk(files)

    # Generate impact sentence.
    impact_tpl = rng.choice(_IMPACT_TEMPLATES[domain])
    n = rng.randint(10, 5000)
    # frontend templates use {browser}; fill it if needed.
    impact = impact_tpl.format(n=n, svc=rng.choice(SERVICES), browser=rng.choice(BROWSERS))

    return {
        "id": ticket_id,
        "files_changed": files_changed,
        "risk_level": risk_level,
        "impact": impact,
        "tests_after": "all passed",
        "verdict": "fix_verified",
    }


def generate_incident_history(ticket_rows: list[dict], seed: int) -> list[dict]:
    """Generate a parallel incident-history record for each row in *ticket_rows*.

    The RNG is seeded with *seed* so the output is fully deterministic.
    """
    rng = random.Random(seed)
    history: list[dict] = []
    for row in ticket_rows:
        history.append(_generate_incident_row(row["id"], row["domain"], rng))
    return history


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

def generate(n_per_domain: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    domains = list(TEMPLATES.keys())
    rows: list[dict] = []
    ticket_id = 1
    seen_titles: set[str] = set()

    for domain in domains:
        templates = TEMPLATES[domain]
        slots = DOMAIN_SLOTS[domain]
        count = 0
        attempts = 0
        max_attempts = n_per_domain * 50

        while count < n_per_domain and attempts < max_attempts:
            attempts += 1
            title_tpl, desc_tpl = rng.choice(templates)
            title = _fill(title_tpl, slots, rng)
            if title in seen_titles:
                continue
            seen_titles.add(title)
            description = _fill(desc_tpl, slots, rng)
            rows.append({
                "id": f"T-{ticket_id:04d}",
                "title": title,
                "description": description,
                "domain": domain,
            })
            ticket_id += 1
            count += 1

        if count < n_per_domain:
            raise RuntimeError(
                f"Could not generate {n_per_domain} unique tickets for domain '{domain}' "
                f"after {max_attempts} attempts (got {count})."
            )

    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "title", "description", "domain"])
        writer.writeheader()
        writer.writerows(rows)


def write_incident_history_csv(rows: list[dict], path: Path) -> None:
    """Write incident-history rows to *path* as CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["id", "files_changed", "risk_level", "impact", "tests_after", "verdict"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    root = Path(__file__).parent.parent

    train_rows = generate(n_per_domain=40, seed=42)
    write_csv(train_rows, root / "data" / "tickets.csv")
    print(f"Wrote {len(train_rows)} rows to data/tickets.csv")

    eval_rows = generate(n_per_domain=10, seed=99)
    write_csv(eval_rows, root / "data" / "eval_tickets.csv")
    print(f"Wrote {len(eval_rows)} rows to data/eval_tickets.csv")

    # Combine both sets and generate incident history (deterministic, seed=7).
    all_rows = train_rows + eval_rows
    history_rows = generate_incident_history(all_rows, seed=7)
    write_incident_history_csv(history_rows, root / "data" / "incident_history.csv")
    print(f"Wrote {len(history_rows)} rows to data/incident_history.csv")
