📎 *New Claude Code skill: `slack-send` — messages & files to Slack directly*

The built-in Slack connector can read Slack and post text, but *can't upload files*. This skill adds that — send a message *or* a file to a DM/channel/thread straight from Claude Code, posted *as you* (not a bot).

*What it does*
• `/slack-send <target> <message>` — e.g. `/slack-send @davit "build is green"`
• `/slack-send <target> <file>` — e.g. `/slack-send #dev-reports ~/Desktop/report.pdf`
• Or just say: _"dm @davit on slack: build green"_ / _"send ~/Desktop/x.pdf to #dev"_
• Targets: `me`, `@teammate`, `#channel`, or a raw ID — thread-aware
• Messages work via MCP even without setup; *files* need the one-time token below
• Bonus: *review-pr-slack* now auto-posts the verdict + attaches its HTML report into the thread 🎉

*Setup (~1 min, once)*
1. Unzip the attached bundle, then run `cd slack-send && bash install.sh`
2. A browser opens → click *Allow* (be signed into m-oneteam Slack). Done — the token is captured automatically.

No admin page, no copy-paste. Full guide in the zip's `README.md`. Token stays local (chmod 600), acts as you, revocable anytime.

Questions → ping me. 🙌
