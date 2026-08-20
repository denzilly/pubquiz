# Kerigorrical Quiz Archive

A local, offline archive and player for the pub quizzes that u/Kerigorrical posts
on [r/KerigorricalQuiz](https://www.reddit.com/r/KerigorricalQuiz/) — so you can
run a quiz night without fighting Reddit's and Imgur's interfaces.

Each quiz plays as a full-screen slideshow of the original slides, then the
answers slideshow, then you record a score against a name. Scores persist to a
local scoreboard.

## Quick start

```bash
python scrape/scrape.py all
```

```bash
python server.py
```

Then open <http://127.0.0.1:8787>. No dependencies — Python 3 standard library only.

## How the archive is put together

Each quiz is a Reddit post that links an Imgur album of slide images. The answers
live in a **second** Imgur album, linked from a comment the quiz author leaves on
their own post. The scraper follows that chain:

| Stage | What it does | Output |
| --- | --- | --- |
| `discover` | Pages the subreddit's Atom feed for every post | `data/posts.json` |
| `resolve` | Reads each post's comments to find the question and answer albums | `data/posts.json` |
| `download` | Pulls both albums' images from Imgur, in order | `data/quizzes/<slug>/` |
| `index` | Builds the manifest the web app reads | `data/index.json` |

Run stages individually if you want:

```bash
python scrape/scrape.py resolve --limit 10
```

The slides are kept **as images** — nothing is OCR'd. A pub quiz has picture
rounds, logos and mash-ups, so the slide *is* the question.

### Re-running is safe

Every stage is resumable and skips work already done. When a new quiz is posted,
just run `python scrape/scrape.py all` again — it fetches only what is missing.

If a quiz is missing because Reddit was throttling during the first run, re-check
just those posts (cheap — it skips everything that already worked):

```bash
python scrape/scrape.py resolve --retry-empty
```

`--force` re-resolves every post from scratch, which takes as long as a first run.

### Running it on another machine

`data/posts.json` is committed, so a fresh clone already knows about every post
on the subreddit and skips the discovery stage. Just run the scrape there:

```bash
python scrape/scrape.py all
```

It resumes from whatever is already in `posts.json` and only fetches what is
missing. The downloaded images and `data/index.json` are not committed — the
`download` stage recreates them.

### About the speed

Reddit rate-limits unauthenticated requests hard from most IPs, so the scraper
deliberately crawls: it waits ~20 s between Reddit requests and backs off
exponentially on HTTP 429. A full first run takes on the order of an hour, mostly
idle waiting. Imgur is much more generous, so image downloads are quick. Progress
is written to disk continuously — stop it with Ctrl+C and rerun to pick up where
it left off.

## Playing a quiz

- Click a quiz on the home page to start the question slideshow.
- <kbd>←</kbd> / <kbd>→</kbd> or <kbd>Space</kbd> to move between slides, or click
  the left/right edge of the slide.
- <kbd>F</kbd> toggles fullscreen — worth using if you are presenting to a room.
- On the last question slide, **Reveal answers** starts the answers slideshow.
- On the last answer slide, **Enter score** opens the score form.
- Scores default to "out of 25", which is the standard for these quizzes (one
  point per question, with Q10 and Q19 carrying extra parts). Change the "out of"
  field for the specials that differ.

The home page marks quizzes you have already played, and the search box filters
by number or topic.

## Layout

```
scrape/scrape.py   the four scrape stages
scrape/net.py      polite HTTP with adaptive rate limiting and backoff
server.py          static file server + score API
web/               the player UI (plain HTML/CSS/JS, no build step)
data/quizzes/      downloaded slides, one directory per quiz
data/index.json    manifest consumed by the web app
data/scores.json   your scoreboard
```

`data/quizzes/` and `data/scores.json` are gitignored — the images are large
(~5 MB per quiz) and can always be re-fetched.

## Notes and limits

- A few posts are not standard quizzes (announcements, "no quiz this week"), and
  a couple of the recent Christmas specials are posted as **Reddit galleries**
  rather than Imgur albums. Those are skipped: they have no Imgur album to
  follow, so they will not appear in the archive.
- The scoreboard is a plain JSON file. Delete `data/scores.json` to reset it.
- The server binds to `127.0.0.1` by default. Pass `--host 0.0.0.0` if you want
  other devices on your network to reach it, e.g. to run the quiz from a laptop
  and let people check the scoreboard on their phones.

## Password protection

Anything beyond localhost should have a password on it — the score API accepts
writes, so an open instance can have its scoreboard filled with junk. Set
`PUBQUIZ_PASSWORD` and the whole site goes behind HTTP Basic auth:

```bash
PUBQUIZ_PASSWORD='something-long' python server.py
```

The username defaults to `quiz`; override it with `PUBQUIZ_USER`. With no
password set the server stays open, which is what you want on localhost — and it
prints a warning if you bind it to a non-local address without one.

It is read from the environment rather than a `--password` flag so it does not
appear in `ps` output or your shell history. For the Docker deploy, put it in a
`.env` file next to `docker-compose.yml` (gitignored):

```bash
printf 'PUBQUIZ_PASSWORD=something-long\n' > .env
```

`docker compose up -d` refuses to start if that variable is missing, so a
public deploy cannot accidentally come up unprotected. `/healthz` stays
unauthenticated — it is the container healthcheck and returns nothing but
liveness.

Basic auth sends the password base64-encoded, not encrypted, so it is only
meaningful over HTTPS. That is fine behind Caddy or a Cloudflare Tunnel, which
terminate TLS for you; do not rely on it over plain HTTP.

## Credit

All quiz content is by [u/Kerigorrical](https://www.reddit.com/user/Kerigorrical),
who also has a [Patreon](https://www.patreon.com/kerigorrical). This is a personal
archiving tool for quizzes that were published publicly — it just makes them
pleasant to play offline.
