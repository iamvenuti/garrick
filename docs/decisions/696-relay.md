---
concept: Relay
issue: https://github.com/iamvenuti/garrick/issues/696
---

# Relay

**The concept.** A relay is the service that gives the Mac one public address so that an assistant in the cloud can reach it; in this release it carries the traffic and cannot read it, because the connection ends on the Mac.

**What it touches.** It touches Remote access and what leaves the Mac. The address is kept and is the sign-in's issuer and resource, so a changed address means adding the connector again. An address the owner already has is the other adapter, and the server behind it can read what passes.

**What was measured.** Tests against a stand-in relay on localhost: setup, address read-back, a lost relay and a changed address. A real relay on a clean Mac is not measured and is named open.

**What would show it is wrong.** A page that says a relay cannot read the traffic when the method does not end the connection on the Mac, or an address that changes without the App showing what it breaks.
