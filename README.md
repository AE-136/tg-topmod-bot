# Telegram Topic Moderator

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Telegram Bot API](https://img.shields.io/badge/Telegram%20Bot%20API-21.6-26A5E4)

> **AI disclosure:** This project — including the code and this README — was
> generated with the help of an AI assistant (Claude, by Anthropic). Review
> the code before relying on it in production.

A Telegram bot for groups with **topics** enabled. It lets you assign, per
topic, a specific list of users who are allowed to post there. Messages from
anyone else are deleted automatically as soon as they're sent. Everything is
configured directly in Telegram — no external dashboard required.

## Features

- Per-topic write access control, independent for each forum topic.
- "Whitelist" mode: until users are explicitly allowed for a topic, anyone
  can post there. After the first user is allowed, only listed users can.
- Rule management right in the chat: `/allow`, `/disallow`, `/open_topic`,
  `/topic_status`, `/rules`, `/whitelist`.
- Configuration commands are restricted to group administrators.
- `@all`: mention everyone relevant to the current topic in one message —
  see [Mentioning everyone with `@all`](#mentioning-everyone-with-all) below.
- Also works in regular groups without topics — the whole group is then
  treated as a single ("General") topic.
- Rules are stored in SQLite; the database path is configurable via an
  environment variable.

## How it works

As long as the bot is an admin in the group, Telegram forwards it every
message regardless of the group's privacy setting (this is how admin bots
behave on the Bot API). For each incoming message (except the bot's own) the
bot looks at `chat_id` and `message_thread_id` (the topic id), records the
author as "seen" in that group, checks the stored rules, and if the author
isn't on the allowed list for that topic, calls `deleteMessage`. The bot's
own messages are never checked against the rules or recorded as "seen" — it
isn't a member to track, and it's never added to any topic's whitelist, so
without this exclusion its own replies in a whitelist topic would get
deleted as unauthorized.

## Requirements

- Python 3.10+
- A bot token from [@BotFather](https://t.me/BotFather)
- The bot must be a group administrator with at least the **"Delete
  messages"** permission
- To restrict actual forum topics, **Topics** must be enabled in the group
  (Group settings → Topics)

## Installation and running

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
pip install -r requirements.txt

export BOT_TOKEN="your_token_from_BotFather"
python bot.py
```

The bot uses long polling, so the process needs to stay running
continuously — running it locally is only meant for testing before you
deploy it somewhere that keeps it alive.

## Configuration

Environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | yes | — | Bot token from BotFather. The aliases `API_TOKEN` and `TELEGRAM_BOT_TOKEN` are also accepted, for compatibility with some hosting platforms. |
| `DB_PATH` | no | `./bot_data.db` | Path to the SQLite database file holding the access rules. Set this explicitly if your hosting platform wipes files next to the script on redeploy. |

## Roles

- Configuration commands (`/allow`, `/disallow`, `/open_topic`, `/rules`,
  `/whitelist`) only work for Telegram **group administrators**. A regular
  member gets an explicit "not allowed" reply.
- Once a topic has switched to whitelist mode (after its first `/allow`),
  an administrator must **also** be explicitly listed in that topic's
  whitelist to keep managing it there — otherwise the bot silently ignores
  their command, no reply at all, even though they're a group admin. While
  a topic is still open (nobody added yet), any admin can run the first
  `/allow` — that's how a topic gets locked down in the first place.

## Bot commands

All commands are sent **inside the topic** you're configuring (except
`/rules`, which reports on the whole group).

| Command | Who can run it | Action |
|---|---|---|
| `/allow` (as a reply to a user's message) | any group admin, if the topic isn't locked yet; otherwise only admins already whitelisted here | Allows the author of that message to post in the current topic. The topic switches to "whitelist" mode. |
| `/allow <user_id> [name]` | same as above | Same thing by numeric ID, if you don't have a message from that user to reply to. |
| `/disallow` (as a reply to a user's message) | same as above | Removes the user from the allowed list for the current topic. |
| `/open_topic` | same as above | Clears the write restriction — the topic is open to every group member again. |
| `/topic_status` | anyone | Shows the current mode of the topic and the list of allowed users, for this topic only. |
| `/rules` | any group admin | Lists all configured topics and their modes for the whole group. |
| `/whitelist` | any group admin | Lists the users in the whitelist of the **current** topic only. |

## Mentioning everyone with `@all`

If an allowed message contains the standalone word `@all`, the bot replies
with mentions in that same topic:

- **Whitelist topic** — mentions only the users in that topic's whitelist.
- **Open topic** (no whitelist yet) — mentions every user the bot has ever
  seen post in the group, in any topic.

A message from a user who isn't allowed to post is deleted as usual and
never triggers `@all` — only messages that are allowed to stay can ping
people. The sender is never included in their own `@all` mentions.

Mentions use `tg://user?id=<id>` links rather than plain `@username` text,
so people without a public username still get notified; long lists are
split across multiple messages to stay under Telegram's message-length
limit.

**Platform limitation:** the Telegram Bot API has no endpoint for a bot to
list every member of a group — this is a Telegram restriction, not a
limitation of this code. So "everyone in the conversation" in an open topic
really means *everyone the bot has personally seen post a message* since it
joined the group, not the group's actual member list from its settings. A
member who has never posted anything won't be mentioned until they do.

## Deployment

The bot is a regular long-running Python process, so it works on any hosting
that supports that (a VPS, systemd, Docker, or a dedicated bot-hosting
platform). One thing to watch for on platforms with an ephemeral filesystem
(where redeploying rebuilds the container and wipes local files): point
`DB_PATH` at a persistent disk/volume if the platform offers one, otherwise
your rules will reset on every redeploy.

## Telegram Bot API limitations

The bot can't look up an arbitrary user by `@username` unless that user has
previously appeared in a chat the bot can see. The reliable way to grant
access is to reply to an existing message from that person with `/allow`. If
they haven't posted yet, use their numeric `user_id` instead (you can get it
from a bot like [@userinfobot](https://t.me/userinfobot)).
