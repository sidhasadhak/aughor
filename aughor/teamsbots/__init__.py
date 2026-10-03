"""Microsoft Teams as a door to a custom agent (Arc AO-5c) — a Bot Framework channel.

The Microsoft grant the integrations catalogue already holds is Graph (mail, profile); a
bot in Teams is a different thing: an Azure Bot registration (an app id and a password)
whose messaging endpoint is THIS API, receiving Activities signed by the Bot Framework and
replying through the Bot Connector at the activity's own `serviceUrl`. Three modules, one
job each — the record (`store`), the signature (`verify`), the reply (`reply`) — so a test
can substitute one function, as `slackbots/verify.py` lets it.
"""
