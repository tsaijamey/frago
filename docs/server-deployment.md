# Running frago on a server

*Added 2026-08-17.*

frago is built for one machine and one owner. Every part of its HTTP surface
assumes that: `/api/file` reads and writes any absolute path, `/api/agent`
starts an agent, `/api/recipes/{name}/run` executes a script. On loopback that
is the point — it is what makes the suit fit.

Put the same server on a machine that is reachable from elsewhere and it is a
shell without a password. This page is how to deploy one anyway: what the server
enforces on its own, what the reverse proxy must not forward, and how your local
frago talks to it.

Three capabilities come out of it:

- **your local frago can hand work to the server's frago** (`frago remote`)
- **the server can show a recipe's page to the public** (`frago recipe expose`)
- **visitors can sign in, and each gets their own copy of a page's data**
  (`frago recipe expose --require-identity`, `frago user`)

Nothing else is exposed.

One thing to hold onto before any of the detail: **the server token is
equivalent to running commands on the box.** It opens `/api/file` (read and
write any absolute path), `/api/agent` (start an agent) and
`/api/recipes/<name>/run` (execute a script). There is no reduced-privilege
mode. Treat it like an SSH key, not like an API key — which is also why the
recommended way to reach the control plane is an SSH tunnel rather than a
public endpoint.

## The four zones

Every request the server receives is sorted into one of four zones by
`frago.server.security.AccessZoneMiddleware`, before any route sees it.

| Zone | What it covers | What it requires |
|---|---|---|
| **trusted local** | a process on this machine — the CLI, the desktop client, a recipe calling back in — and, by default, other devices on the private network | nothing; behaviour is unchanged from a personal install |
| **public** | `GET /app/<recipe>/…` for a recipe published in `public` mode | nothing, but it is read-only and the page's config is filtered |
| **identity** | the same pages for a recipe published in `identity` mode, plus five `/api/auth/…` endpoints (login, logout, password, me, pages) | a login cookie; still read-only, still filtered, and the visitor reads *their own* slot |
| **private** | everything else: all of `/api`, `/ws`, `/viewer`, `/browser`, the SPA | `Authorization: Bearer <token>` |

A signed-in visitor is **not** a reduced-privilege owner. They reach published
pages and nothing else: `/api/file`, `/api/agent` and `/api/recipes/<name>/run`
are each equivalent to running code on the box, and only the token opens them.
The only anonymous entry point the identity zone adds to the public surface is
`POST /api/auth/login`; logging out, changing a password and `GET /api/auth/me`
all require a session that already exists.

"Trusted local" means two things at once: the peer address is one frago counts
as home, **and** the request carries no proxy forwarding headers
(`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `CF-Connecting-IP`, …). That
second half is what makes the zone survivable on a deployed box — a reverse
proxy on the same machine also connects from 127.0.0.1, and without the header
check everything it forwards from the internet would inherit the owner's
unconditional trust. The rule only ever moves a caller from trusted to
untrusted, so a forged header costs the sender their own privileges and gains
them nothing.

But a header list is a guess about somebody else's software, and some proxies
do not forward at the HTTP layer at all — an SSH tunnel, `docker -p`, socat, or
an nginx `proxy_pass` written without `proxy_set_header` carry no headers to
inspect. To frago, a visitor arriving that way is indistinguishable from you
typing curl on the machine itself.

**A deployment that does not set `FRAGO_BEHIND_PROXY=1` is known-unsafe, not
merely unhardened.** This was measured, not theorised: through a plain TCP
forwarder, `POST /api/agent` reached its route with no token asked for. With the
variable set, frago stops inferring trust from the peer address altogether —
published pages stay public, everything else needs the token, whatever arrives
in the headers.

nginx and HAProxy are the two to watch: neither sets forwarding headers unless
you write `proxy_set_header` / `option forwardfor` yourself. Caddy, Traefik,
Apache and Cloudflare happen to set them by default — but "safe because of
someone else's default" is not a property to build on.

"Home" is loopback plus, by default, the private network. That default is not a
shrug: frago binds `0.0.0.0` out of the box, `frago server status` prints the
LAN URLs it can be reached at, and reading the workbench from your phone is a
feature the tool advertises. Turning it off by default would break every
personal install to protect a deployment that step 1 below already protects
better. On a server, turn it off.

## Server setup

**1. Tell frago it is on a server.** The defaults are right for a home machine
and wrong here. Three lines:

```bash
export FRAGO_SERVER_HOST=127.0.0.1   # only the proxy can open a socket
export FRAGO_TRUST_LAN=0             # a neighbour in the VPC is not the owner
export FRAGO_BEHIND_PROXY=1          # never infer trust from the peer address
frago server restart
```

These are the most valuable lines on this page, and they are deliberately
redundant. The first keeps the internet off the socket, the second keeps the
private network off it, and the third means that even if both are somehow wrong
— a misconfigured proxy, a container network you did not expect, a header your
proxy does not set — the only thing an anonymous caller can still reach is a
page you published on purpose.

**2. Mint the token.**

```bash
frago server token           # prints it; creates it on first call
```

It lands in `~/.frago/server-token`, mode 0600. `--rotate` invalidates every
remote holding the old one.

**3. Publish only what should be public.**

```bash
frago recipe expose weekly_report
frago recipe exposed          # what strangers can currently read
```

`expose` prints what the exposure actually amounts to before it does anything:
whether the slot declares a `public` block, and how many files sit under the
`dataDir` that becomes readable.

## Letting visitors sign in

A page exposed the way above shows every visitor the same bytes, because the
public zone has no notion of a person. If you want two visitors to see two
different sets of data — a trainer that remembers where each person got to, a
form each person fills in for themselves — expose it in identity mode instead:

```bash
frago recipe expose kline_trainer --require-identity
```

Anonymous requests to that page now get a 401. Someone who signs in gets the
same page, filtered exactly as hard as the public one, reading the slot named
after their own account.

### The front door

That 401 is written for a machine — it names a token the visitor neither has
nor should have. So a person arriving in a browser is moved to the sign-in page
instead: `302` to `/app/<portal>/?next=<recipe>`, and the portal hands them back
to the page they wanted once they are in.

Which page is the door is named, never inferred — `FRAGO_LOGIN_PORTAL`,
defaulting to `frago_login_portal`. Set it to the empty string to switch the
redirect off and restore the plain 401.

```bash
export FRAGO_LOGIN_PORTAL=frago_login_portal   # the default; name your own if it differs
```

The portal is a recipe you write, not something frago ships, and it has to be
exposed in `public` mode itself — a door nobody can open is not a destination,
just a second 401. Four conditions gate the redirect, and each closes a way it
could mislead: only a top-level HTML navigation (`Accept: text/html`, GET or
HEAD), so a page's own `fetch` still gets JSON rather than a login form; only
identity-mode published pages, so a refusal for some other reason is not
dressed up as "you should sign in"; never the portal itself and never a portal
that is not anonymously readable, both of which would loop; and the target is
always a path on this site. The response carries `no-store`, because what this
address answers depends on who is asking.

There is no registration step: the first time an address is used, that account
is created with whatever password came with it. Deliberately, and with two
consequences that cannot be patched out — **an address is a handle, not proof**
(nobody verifies it, so whoever signs in with an address first holds it here),
and **the existence of an account is discoverable** (a fresh address gets in, a
known one with a wrong password does not). Do not hang anything valuable on one
of these identities. There is no password recovery either; you reset it.

Five environment variables shape it. The first two are what stop the account
table from being filled by a script:

```bash
export FRAGO_TRUSTED_PROXIES=127.0.0.1   # whose forwarding headers to believe
export FRAGO_SIGNUP_GATE='pear-lamp-42'  # a shared passphrase for new accounts
export FRAGO_PUBLIC_HTTPS=1              # "visitors reach me over TLS"
export FRAGO_SESSION_TTL=604800          # 7 days, absolute, no sliding renewal
export FRAGO_MAX_USERS=500               # hard ceiling on the account table
```

`FRAGO_TRUSTED_PROXIES` is the load-bearing one, and it pairs with
`FRAGO_BEHIND_PROXY=1` from step 1. With that switch set, frago refuses to guess
who the client is: unless you name the proxies, per-address rate limiting
declares itself unavailable rather than counting a value the caller controls —
and then `FRAGO_SIGNUP_GATE` stops being optional. **This only works when the
proxy hop reaches frago over loopback**, which is what step 1's
`FRAGO_SERVER_HOST=127.0.0.1` arranges. A proxy on another machine is a hop
uvicorn does not rewrite addresses for, so treat address-based limiting as
absent there and set the passphrase.

`FRAGO_PUBLIC_HTTPS=1` says the address you hand out is `https://`. With it set,
a login arriving over plain HTTP is refused outright rather than answered with a
session cookie that anyone on the path could copy — relevant here because the
HTTPS sidecar (`FRAGO_SSL_CERTFILE`/`FRAGO_SSL_KEYFILE`) leaves port 8093 up
alongside it, and same-site-different-scheme is not cross-site, so `SameSite`
protects nothing there.

The passphrase travels in the request body, never in the URL: a URL ends up in
proxy access logs, browser history and `Referer`. Put it next to the link when
you share it, not inside it.

## Account operations

`frago user` is the owner's view of the people who signed in. It is not
`frago whoami` (this frago's own cloud account) and not `frago session` (agent
transcripts on this machine).

```bash
frago user list                    # id ↔ email, every line marked unverified
frago user list --recent           # ordered by who was here last
frago user passwd <id|email>       # hidden prompt; also logs that person out everywhere
frago user disable <id|email>      # takes effect on their next request, not at expiry
frago user enable  <id|email>
frago user session list            # who is signed in right now
frago user session revoke <id>     # cut one login short
```

Four things worth knowing before you need them:

- **The password is only ever typed at a prompt.** There is no `--password`
  flag: an argument is visible to every other account on the box through
  `ps -ww`, and then lives on in shell history.
- **Changing a password logs that account out everywhere.** That is the point
  rather than a side effect — with no recovery flow, a reset is how a stolen
  cookie is dealt with, and one that spared live sessions would not deal with it.
- **Disabling suspends, it does not delete.** The account id is also the name of
  that person's data slot; deleting the row would orphan the data and hand it to
  whoever next signs in with that address.
- **Session ids in the listing are hashes, not cookies.** Printing one cannot
  let anyone in; it is what `revoke` takes.

Two files hold all of this — `~/.frago/users.json` (0600) and
`~/.frago/login-sessions/` (0700, one file per login). Both are covered by the
startup permission repair. Deleting the session directory signs everyone out and
breaks nothing else.

## Reverse proxy

One prefix goes through. Everything else is a 404 at the edge:

```nginx
# One bucket per client address. 5r/m is generous for a human typing a password
# and ruinous for a script: signing in is the one anonymous request that makes
# this server compute an scrypt hash and write two files.
limit_req_zone $binary_remote_addr zone=frago_login:10m rate=5r/m;
# Page loads are cheap reads off the disk, so this one is only about volume.
limit_req_zone $binary_remote_addr zone=frago_pages:10m rate=30r/s;

server {
    listen 443 ssl;
    server_name recipes.example.com;

    # ssl_certificate ... ;
    # ssl_certificate_key ... ;

    location /app/ {
        limit_req zone=frago_pages burst=60 nodelay;
        proxy_pass http://127.0.0.1:8093;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Only needed for identity-mode pages. The gate whitelists five exact paths
    # under this prefix (login, logout, password, me, pages) and 401s anything
    # else, so forwarding the prefix adds no reachable endpoint.
    location /api/auth/ {
        limit_req zone=frago_login burst=5 nodelay;
        proxy_pass http://127.0.0.1:8093;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        return 404;
    }
}
```

Setting the forwarding headers is not optional politeness — it is how the server
knows these requests are not local, and `X-Forwarded-Proto` is how it knows to
mark the session cookie `Secure`. Keep them.

The `limit_req` lines are the volumetric layer, and they belong here rather than
in frago: refusing a flood at the edge costs nginx a comparison, while refusing
it in frago costs a Python request cycle per attempt. frago's own limits — the
per-address buckets, the per-account backoff, the account caps — assume this
layer exists above them and protect against a different thing: the patient
attacker who stays under any rate you would be willing to set.

That gives three independent layers between the internet and the machine: the
proxy forwards one prefix, the middleware allows one method on one zone, and the
published list names the recipes. Any one of them failing on its own leaks
nothing.

## Talking to it from your own machine

The control plane stays off the public internet. Reach it over SSH:

```bash
ssh -L 18093:127.0.0.1:8093 box
```

Then, locally:

```bash
frago remote add box --url http://127.0.0.1:18093 --token <token>
frago remote status box
frago remote send box "跑 weekly_report，产出发布到 /app/weekly_report"
frago remote chat box
```

`remote send` posts one brief to the server's PA and waits for its reply. Write
briefs as outcomes plus hard constraints, not as command sequences: the remote
PA reads them with that machine's own hook rules and knowledge loaded, and it is
the only one of the two that knows what is installed there.

The token is still required over the tunnel. It is what stops another account on
either box from steering the agent.

### If you must expose the control plane

Prefer the tunnel. If you genuinely need token-only access without one, give it
its own vhost and its own three locations — `/api/pa/chat`, `/api/status`,
`/ws` — and nothing more. Never proxy `/api/` as a prefix: `/api/file` and
`/api/agent` live under it.

```nginx
server {
    listen 443 ssl;
    server_name control.example.com;

    # A browser cannot set headers on a WebSocket handshake, so the token
    # travels in the query string here — and nginx logs `$request` in full.
    # Logging this line writes a credential equivalent to shell access into
    # your log pipeline.
    location /ws {
        access_log off;
        proxy_pass http://127.0.0.1:8093;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header X-Real-IP  $remote_addr;
    }

    location = /api/pa/chat { proxy_pass http://127.0.0.1:8093; proxy_set_header X-Real-IP $remote_addr; }
    location = /api/status  { proxy_pass http://127.0.0.1:8093; proxy_set_header X-Real-IP $remote_addr; }

    location / { return 404; }
}
```

Holding this token is equivalent to running commands on the server: it opens
`/api/agent`, `/api/recipes/{name}/run` and `/api/file`. Treat it as an SSH key,
not as an API key — which is the other reason the tunnel is the better answer.

## What a published page can and cannot do

A published page gets its `assets/`, the `public` block of its slot state, and
the files under that slot's `dataDir`. Its `config.json` arrives with
`apiBase: null` and `readOnly: true`.

Recipe front ends written for a personal machine commonly call
`${apiBase}/recipes/<name>/run` and `${apiBase}/file?path=…`. Those calls run a
script on the server and read arbitrary paths off its disk, so they are closed
to visitors and will fail. A recipe meant for the public computes its results
into `dataDir` and renders them; the front end checks `readOnly` and hides
whatever would have posted.

Slot state itself is not published wholesale, because it routinely holds
absolute paths and sometimes holds credentials. Declare what a visitor may see:

```python
from frago.recipes.app_state import publish

publish("weekly_report", {
    "dataDir": str(out_dir),                  # private: how files are found
    "public": {"title": "Q3 numbers"},        # public: what the page is told
})
```

Publishing one slot publishes only that slot. A recipe holding a public
dashboard in `default` and a client's working set in `acme` stays safe.

An identity-mode page works the same way with one difference: which slot the
visitor reads is decided by the server from their session, never by anything in
the request. Everything one account owns lives in one subtree —
`~/.frago/users/<account id>/state/<recipe>.json` for their slots and
`~/.frago/users/<account id>/data/<recipe>/` for anything a run produced for
them — kept apart from the recipe's own root so a recipe writing a slot of its
own can never land on a file belonging to a visitor. A visitor whose recipe has
not written anything for them yet sees an empty state, which the page must
render rather than crash on.

## Opening a page to named people, and letting them run it

`--allow` narrows an identity page from "anyone who signs in" to a list of
accounts. Anyone not on it — signed in or not — gets the same 401 as if the page
had never been published, so the refusal is not a way to discover that the page
exists.

```bash
frago user list                                  # ids ↔ emails
frago recipe expose venture_ledger --allow <account id> --yes
```

The list holds account ids. An email is accepted only as a lookup convenience
and only if somebody has already signed in with it: nothing here verifies an
address, so writing an unclaimed one would not authorise a colleague, it would
hang a first-come ticket on the public internet.

Every run of `expose` states the page's exposure in full, so a flag left off is
a flag turned off. That is right for every flag but this one: adding
`--runnable` to a page that has an allow list, without repeating `--allow`,
would reopen it to everyone who can sign in — and the command that does it
looks exactly like the command that only meant to change something else. That
one widening is refused, with the accounts it would drop named in the error.
Say `--force` if opening the page up is what you meant. It is deliberately not
folded into `--yes`: `--yes` is the automation path documented on this page, so
a script that habitually carries it would sail straight through. Narrowing a
list, naming the same people again, a first publish, and public-mode pages are
all untouched.

```bash
frago recipe expose venture_ledger --allow <id-a> --allow <id-b> --runnable --yes   # keep the list
frago recipe expose venture_ledger --require-identity --force --yes                 # drop it, on purpose
```

`--runnable` goes further and lets those visitors trigger a run. Three things to
weigh before using it:

**The recipe must take the directory it is handed.** One line, no import:

```python
data_dir = os.environ.get("FRAGO_RECIPE_DATA_DIR") or <its own old default>
```

Without it every visitor's run writes the owner's directory and they all share
one pile. `expose --runnable` refuses a recipe whose source never mentions that
variable, and `frago recipe validate` re-checks it afterwards, for the case where
someone edits the line back out while the page keeps its permission.

**The run uses your machine and your credentials.** `FRAGO_SECRETS` is keyed by
recipe; there is no "whose" dimension. A visitor-triggered run holds whatever you
configured for that recipe. So the question is not whether the recipe has bugs —
it is whether its source is something you would hand a stranger a button for.
Never make a recipe runnable if it spends money or acts as you: placing orders,
posting, mailing, calling a metered API.

**It is not a sandbox.** The recipe runs as the server's user with the server's
permissions. The isolation here covers where output lands, nothing more.

What the page sees: `POST /app/<name>/run` with `{"params": {…}}` answers 202
`{"accepted": true}` and nothing else — never the recipe's return value, which
routinely carries absolute paths. Progress and outcome are read back from the
visitor's own directory, where the platform maintains `data/run.json`
(`running` / `done` / `failed`; the name is reserved, recipes must not write it).
Parameters are checked strictly for visitors: undeclared keys are refused, and
`enum` / `max_length` / `pattern` / `min` / `max` are enforced. One run at a time
per person per page; a second gets 409. Visitor runs also have their own, smaller
concurrency limit, so a few visitors cannot take every worker and leave the
owner's machine unresponsive.

Rate-limit `/app/` at the proxy when using `--runnable`. The platform limits
concurrency, not frequency, and a request under that prefix now starts a process
rather than reading a file.

A signed-in visitor can ask `GET /api/auth/pages` which pages are theirs to open.
It answers with names, titles and whether each is runnable — never with the allow
list, which is not the visitor's business.
