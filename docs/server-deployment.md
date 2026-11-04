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
- **the server can show a recipe's page to people who are not you**
  (`frago recipe expose --public`, `--signed-in`, `--allow`)
- **signed-in visitors read their own copy of a page's data, or one shared
  reading of it** (`--each-their-own`, `--shared`, `frago user`)

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

The zones are named `local`, `public`, `identity` and `token` in the code, and a
value outside that set is refused rather than read as the most permissive one.

| Zone | What it covers | What it requires |
|---|---|---|
| **local** | a process on this machine — the CLI, a recipe calling back in — and, only with `FRAGO_TRUST_LAN=1`, other devices on the private network | nothing; behaviour is unchanged from a personal install |
| **public** | `GET`/`HEAD` on `/app/<recipe>/…` for a recipe published in `public` mode | nothing, but it is read-only and the page's config is filtered |
| **identity** | the same pages for a recipe published in `identity` mode, plus five `/api/auth/…` endpoints (login, logout, password, me, pages) | a login cookie; filtered, and the visitor reads the slot the gate decides for them |
| **token** | everything else: all of `/api`, `/ws`, `/viewer`, `/browser`, the SPA | `Authorization: Bearer <token>` |

A signed-in visitor is **not** a reduced-privilege owner. They reach published
pages and nothing else: `/api/file`, `/api/agent` and `/api/recipes/<name>/run`
are each equivalent to running code on the box, and only the token opens them.
The identity zone's only write entrances are `POST /app/<name>/run` and
`POST /app/<name>/api/<mode>`, and only for a page they are allowed on.

Two entries are anonymous and neither is an auth call: `POST /api/auth/login`,
and `POST /api/teaming` with its WebSocket `/api/teaming/ws` — vibe teaming's
pairing door, where the pairing code itself is the credential and the route,
not the gate, decides whether the code is good. Both are registered as exact
method-and-path pairs rather than prefixes, so no future endpoint joins the
anonymous surface by accident. Logging out, changing a password, `GET
/api/auth/me` and `GET /api/auth/pages` all require a session that exists.

The local zone means two things at once: the peer address is one frago counts
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

"Home" is loopback only, unless `FRAGO_TRUST_LAN=1` adds the private network.
frago binds `0.0.0.0` out of the box and `frago server status` shows the bind
address it is serving on — a caller on the same subnet can reach that, but needs
the token like any other remote caller. Until 2026-09-24 the private network
counted as home by default, which on an office or café subnet handed every
neighbour the owner's seat. Opt in only on a network you actually trust — never
on a server.

## Server setup

**1. Tell frago it is on a server.** The defaults are right for a personal
machine and wrong here. Three lines:

```bash
export FRAGO_SERVER_HOST=127.0.0.1   # only the proxy can open a socket
export FRAGO_TRUST_LAN=0             # already the default; pinned so an inherited =1 cannot undo it
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
frago recipe expose weekly_report --public
frago recipe exposed          # who can open each page, whose data it reads, what it accepts
```

The first exposure **must say who may open the page** — `--public`, `--signed-in`
or `--allow <account>`. There is no default: a bare `frago recipe expose <name>`
is refused and lists the three, because the person who typed the bare command is
exactly the one who has not decided yet, and the answer they used to get was the
widest one.

`expose` prints what the exposure actually amounts to before it does anything:
whether the slot declares a `public` block, and how many files sit in the landing
spot that becomes readable.

## Letting visitors sign in

A page exposed the way above shows every visitor the same bytes, because the
public zone has no notion of a person. Wanting two visitors to see two different
sets of data — a trainer that remembers where each person got to, a form each
person fills in for themselves — is a separate decision from who may open the
page. Exposure answers two independent questions, and mixing them up was this
system's biggest old flaw:

```bash
frago recipe expose kline_trainer --signed-in                     # who may open it
frago recipe expose kline_trainer --signed-in --each-their-own    # whose data they see (the default)
frago recipe expose dma_plan --allow a@x.com --allow b@x.com --shared   # these two read one reading
```

`--require-identity` is still accepted as the old spelling of `--signed-in`.

Anonymous requests to a signed-in page get a 401. Someone who signs in gets the
same page, filtered exactly as hard as the public one, reading the slot the gate
worked out from their session.

The two answers on the data side are physically different files, and neither is
reachable from the other:

| `reads` | Where it lands | Who has a copy |
|---|---|---|
| `own` (default) | `~/.frago/users/<account id>/state/<recipe>.json` | one per signed-in account |
| `recipe` (`--shared`) | `~/.frago/app-state/<recipe>/<slot>.json` | the recipe's own slot — no account anywhere in the path |

`--shared` is read-only by construction: nobody on such a page has a directory of
their own, so `/run` answers 404 and the page's `actions` are empty however many
`@action` modes the recipe marked. It is not the same thing as machine-level
shared data (`shares` / `reads_common`), which is about several *recipes*
reading one another's data.

### The front door

That 401 is written for a machine — it names a token the visitor neither has
nor should have. So a person arriving in a browser is moved to the sign-in page
instead: `302` to `/app/<portal>/?next=<recipe>`, and the portal hands them back
to the page they wanted once they are in.

Which page is the door comes from three sources, in this order:

```bash
frago recipe expose frago_login_portal --public --portal   # register it in published.json
export FRAGO_LOGIN_PORTAL=frago_login_portal               # or override, empty string = off
```

An operator override wins, including an empty value, which switches the redirect
off and restores the plain 401. Otherwise the page registered with `--portal`,
which `frago recipe exposed` shows. Otherwise the historical default name
`frago_login_portal`, so a deployment that never registered one keeps the
behaviour it had.

The portal is a recipe you write, not something frago ships, and it has to be
exposed in `public` mode itself — a door nobody can open is not a destination,
just a second 401. Only one page may be registered as the door; a second attempt
names the current one and is refused.

Four conditions gate the redirect, and each closes a way it
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
frago user passwd <id|email> --temporary   # issue a stand-in, print it once, they must replace it
frago user disable <id|email>      # takes effect on their next request, not at expiry
frago user enable  <id|email>
frago user session list            # who is signed in right now
frago user session revoke <session id>   # cut one login short
```

`--temporary` is the reset-for-somebody-else path: this machine invents the
password and prints it once, and until the holder replaces it that account can
reach exactly two things — who it is, and the form that replaces it. No page, not
even the list of pages. You cannot type a stand-in yourself: that path is called
from a web console, where the argument lands in argv and `ps -ww` shows it to
every other account on the box.

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
the files in the landing spot the platform gives this recipe. Its `config.json`
arrives with `apiBase: null` and `readOnly: true`, plus `actions` — the modes
this page may trigger. The anonymous side does not even get that key.

**Where that landing spot is, the server works out from who is asking**, never
from anything the recipe published. A signed-in reader of a per-person page gets
their own directory; the owner, an anonymous reader of a public page and everyone
on a shared reading all get the machine's own, because all three are looking at
what this machine's runs produced. The page asks for a file by name and the
answer is resolved inside the right root; the path itself never reaches the
client, so a visitor cannot learn the layout of the disk.

Recipe front ends written for a personal machine commonly call
`${apiBase}/recipes/<name>/run` and `${apiBase}/file?path=…`. Those calls run a
script on the server and read arbitrary paths off its disk, so they are closed
to visitors and will fail. A recipe meant for the public computes its results
into its own landing spot and renders them; the front end checks `readOnly` and
hides whatever would have posted.

Slot state itself is not published wholesale, because it routinely holds
absolute paths and sometimes holds credentials. Declare what a visitor may see:

```python
from frago.recipes.app_state import publish

publish("weekly_report", {
    "dataDir": str(out_dir),                  # stays private; nothing reads it to locate files
    "public": {"title": "Q3 numbers"},        # public: what the page is told
})
```

The contract is inverted rather than filtered: a recipe declares what is public
and nothing else leaves the box. Guessing which keys are safe by their names is
the kind of filter that works until it doesn't.

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

`--allow` narrows a page from "anyone who signs in" to a list of accounts.
Anyone not on it — signed in or not — gets the same 401 as if the page had never
been published, so the refusal is not a way to discover that the page exists.

```bash
frago user list                                  # ids ↔ emails
frago recipe expose venture_ledger --allow <account id> --yes
```

The list holds account ids. An email is accepted only as a lookup convenience
and only if somebody has already signed in with it: nothing here verifies an
address, so writing an unclaimed one would not authorise a colleague, it would
hang a first-come ticket on the public internet.

**Re-running `expose` changes only what you name.** Leaving off `--allow` does
not clear the list, and changing `--slot` does not quietly reopen the page.
Widening has to be said out loud, and each widened switch is its own word:

```bash
frago recipe expose venture_ledger --allow <id-b>      # add Bob, keep everyone
frago recipe expose venture_ledger --deny  <id-a>      # take Alice off
frago recipe expose venture_ledger --only  <id-a> --only <id-b>   # exactly these two
frago recipe expose venture_ledger --signed-in         # drop the list, open to every account
```

`--force` is gone, and so is `--runnable`. `--force` existed only to cancel the
side effect of each `expose` rewriting the whole record; with incremental
changes there is nothing left to cancel. Passing either prints what replaced it
and exits non-zero rather than being silently ignored.

### What a page may trigger is the recipe's call, not yours

Whether a page has buttons used to be an exposure flag: `--runnable` meant *who
can see it can press it*, and pressing ran on this machine with your credentials.
One recipe could be runnable on one page and not on another while its own source
said nothing about it. That answer now lives on the recipe, on the methods
themselves:

```python
@export                       # other modules may call it; pages may read it — read-only
def mode_status(self): ...

@action                       # the page may trigger it; it is allowed to do work
def mode_save(self): ...

def mode_backfill(self): ...  # unmarked: owner only
```

One mode, one level. "Both exported and page-triggerable" is not a state: an
exported mode is read-only by contract, so a page reads it with
`POST /app/<name>/api/<mode>` and needs no button. `page_actions` in
`recipe.md` is the retired spelling; `frago recipe validate` names it and says to
move the marks onto the methods.

Exposure still decides who is looking; the recipe decides what may be asked of
it. Both can only be narrowed by the other side's answer, never widened.

Three things to weigh before marking a mode `@action` on a page other people can
reach:

**The recipe must take the directory it is handed.** One line, no import:

```python
data_dir = os.environ.get("FRAGO_RECIPE_DATA_DIR") or <its own old default>
```

Without it every visitor's run writes the owner's directory and they all share
one pile. `frago recipe validate` refuses an `@action` mode in a recipe whose
source never mentions that variable, and re-checks afterwards, for the case
where someone edits the line back out while the page keeps its permission.

**The run uses your machine and your credentials.** `FRAGO_SECRETS` is keyed by
recipe; there is no "whose" dimension. A visitor-triggered run holds whatever you
configured for that recipe. So the question is not whether the recipe has bugs —
it is whether its source is something you would hand a stranger a button for.
Never mark one `@action` if it spends money or acts as you: placing orders,
posting, mailing, calling a metered API.

**It is not a sandbox.** The recipe runs as the server's user with the server's
permissions. The isolation here covers where output lands, nothing more.

What the page sees: `POST /app/<name>/run` with `{"params": {"mode": "save", …}}`
answers 202 `{"accepted": true}` and nothing else — never the recipe's return
value, which routinely carries absolute paths. Progress and outcome are read back
from the visitor's own directory, where the platform maintains `data/run.json`
(`running` / `done` / `failed`; the name is reserved, recipes must not write it).
Parameters are checked strictly for visitors: undeclared keys are refused, and
`enum` / `max_length` / `pattern` / `min` / `max` are enforced. One run at a time
per person per page; a second gets 409. Visitor runs also have their own, smaller
concurrency limit, so a few visitors cannot take every worker and leave the
owner's machine unresponsive.

A recipe with no `@action` mode answers 404 — the same answer as a page that was
never published. A requested mode that is not among them answers 403 and lists
the ones that are. A `--shared` page answers 404 to every run.

Rate-limit `/app/` at the proxy. The platform limits concurrency, not frequency,
and a request under that prefix starts a process rather than reading a file.

A signed-in visitor can ask `GET /api/auth/pages` which pages are theirs to open.
It answers with names, titles and the actions each page accepts — never with the
allow list, which is not the visitor's business.
