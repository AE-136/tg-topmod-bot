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
  `/topic_status`, `/rules`.
- Configuration commands are restricted to group administrators.
- Also works in regular groups without topics — the whole group is then
  treated as a single ("General") topic.
- Rules are stored in SQLite; the database path is configurable via an
  environment variable.

## How it works

As long as the bot is an admin in the group, Telegram forwards it every
message regardless of the group's privacy setting (this is how admin bots
behave on the Bot API). For each incoming message the bot looks at `chat_id`
and `message_thread_id` (the topic id), checks the stored rules, and if the
author isn't on the allowed list for that topic, calls `deleteMessage`.

The bot uses long polling, so the process needs to stay running
continuously — running it locally is only meant for testing before you
deploy it somewhere that keeps it alive.

## Requirements

- Python 3.10+
- A bot token from [@BotFather](https://t.me/BotFather)
- The bot must be a group administrator with at least the **"Delete
  messages"** permission
- To restrict actual forum topics, **Topics** must be enabled in the group
  (Group settings → Topics)

## Configuration

Environment variables:

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | yes | — | Bot token from BotFather. The aliases `API_TOKEN` and `TELEGRAM_BOT_TOKEN` are also accepted, for compatibility with some hosting platforms. |
| `DB_PATH` | no | `./bot_data.db` | Path to the SQLite database file holding the access rules. Set this explicitly if your hosting platform wipes files next to the script on redeploy. |

## Bot commands

All commands are sent **inside the topic** you're configuring.

| Command | Action |
|---|---|
| `/allow` (as a reply to a user's message) | Allows the author of that message to post in the current topic. The topic switches to "whitelist" mode. |
| `/allow <user_id> [name]` | Same thing by numeric ID, if you don't have a message from that user to reply to. |
| `/disallow` (as a reply to a user's message) | Removes the user from the allowed list for the current topic. |
| `/open_topic` | Clears the restriction — the topic is open to every group member again. |
| `/topic_status` | Shows the current mode of the topic and the list of allowed users. |
| `/rules` | Lists all configured topics and their modes for the group. |

All configuration commands are restricted to group administrators.

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
