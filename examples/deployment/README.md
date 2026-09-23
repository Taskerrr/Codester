# Direct-to-production deployment with Docker and pytest

This is a starting point for a Python website, not a deployment of Codester itself.
There is no staging server. Copy `deploy.sh` to `scripts/deploy.sh` in the website
repository and adapt `compose.production.yaml` for that application. Commit both.

The script builds one image, runs pytest in that exact image, replaces the production
application only after success, and checks both the running image and HTTP health.
Build/test failures (including no collected tests) stop before production replacement.
A later startup/health failure reports failure, but production may already have changed.

## Website prerequisites

- A Dockerfile whose default image contains the application, Python, pytest,
  test dependencies and tests, with the correct working directory for `python -m pytest`.
  Its default command must start your website. This deliberately simple version ships
  tests/test dependencies in the runtime image; a separate test image can be added later.
- `.dockerignore` excludes `.git`, local virtual environments, credentials and `.env`
  files, but includes tests and their fixtures. Never bake production secrets into images.
- The Compose application service uses `${CODESTER_DEPLOY_IMAGE}` as its image and has
  a meaningful health check. Do not mount checkout source over the tested application.
  The sample assumes a Python HTTP website listening on port 8000 with `/health`.
- On the Linux server: Docker with Compose v2 supporting `--wait`, Git, Bash, `flock`,
  curl, and an authenticated checkout. Add environment-specific settings to your server
  configuration/Compose file. The script executes non-interactively.

Edit the image repository, Compose filename, service and health URL at the top of
`deploy.sh`. The sample uses `--no-deps` to leave production dependencies alone:
provision your database and other dependencies separately before the first deployment.

Pytest runs without production environment variables, volumes or network access.
For tests that need a database, adapt the test step to start an isolated test database
and network, pass only test credentials, and clean them up on failure. Never run those
tests against the production database. No database migrations are included in this example.

## Configure Codester

In Settings > GitHub > Repository actions:

1. Choose the saved SSH connection and absolute repository-root folder.
2. Select **Repository script**, and enter `scripts/deploy.sh`.
3. Optionally select **Pull latest before running**. It uses the current branch's
   configured upstream and permits only fast-forward updates.
4. Save, then press **Deploy** in the GitHub workspace. Confirmation remains optional.

Codester requires a clean checkout (including untracked files), acquires a server-side
lock in Git's metadata directory, optionally pulls, and invokes the committed script
with Bash error/pipe failure handling. Git-ignored server configuration can remain.
The resolved commit is printed and supplied as `CODESTER_DEPLOY_COMMIT`.
The remote Bash file need not be executable. Use LF line endings.

Each run has a 30-minute limit and retains the last 64 KB of output. An SSH interruption
or timeout has an unknown outcome: the remote process may still be running. Inspect
it before retrying. Do not concurrently edit/pull the checkout or deploy manually.

Custom commands continue to work as before. Script success means exit code zero;
Codester cannot verify which tests an arbitrary repository script actually performs.
The example prints build, test, deployment and health stages into the captured output.

## Previous releases

Unique commit-based tags are retained; the previous container's image is additionally
saved as `my-website:previous`. To roll back manually, set `CODESTER_DEPLOY_IMAGE` to
that tag and run the same Compose `up --no-build --pull never --no-deps --wait` command,
then check health. The script does not roll back automatically. Database migrations
and external side effects need their own compatible recovery procedure.

References: [Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up/)
and [pytest exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html).
