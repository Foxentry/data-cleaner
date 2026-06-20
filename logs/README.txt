LOGS
====
APPLICATION LOG: logs/app.log — a human-readable trace of the run (server
start, run start/finish, progress, retries on 429, errors with traceback).
Check here if something gets stuck. Rotates automatically (2 MB x 3).
Disable with LOG_APP=off in config.env.

REQUEST LOGS: OFF by default — nothing is written here unless you ask for it.
Enable logging for a single run on the Order step, or permanently with
LOG_REQUESTS=on in config.env. When enabled, each Foxentry API call is saved:
  requests-<datetime>.jsonl   one JSON object per call:
      ts        request time
      endpoint  target endpoint (/email/validate, /location/validate, ...)
      status    HTTP response status
      ms         API response time in milliseconds
      request   the exact request body sent
      response  the API response
  requests-<datetime>.csv     same data for Excel (";" separated, UTF-8 BOM):
      time, endpoint, status, ms, query, result, error

The API key is always masked in the logged headers.
Other files: probe.jsonl (estimate probe), requests-cli-<datetime>.* (CLI runs).
Old request logs are deleted after LOG_RETENTION_DAYS (default 7) and can be
wiped any time from the log viewer (Logs).
