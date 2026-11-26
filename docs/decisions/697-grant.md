---
concept: Grant
issue: https://github.com/iamvenuti/garrick/issues/697
---

# Grant

**The concept.** A grant is one connected assistant's standing permission to use remote access: its client, whether it may read, write or both, and its reach, made by a pairing code typed at the consent page and revoked in Settings.

**What it touches.** It touches Reach, which each grant holds, and the sign-in of the remote access extra. Tokens are kept hashed outside the workspace, and a refresh token used twice revokes its grant. No other part of Garrick changes.

**What was measured.** Tests with the MCP SDK's own client on localhost: invalid, expired, revoked and wrong-resource tokens are refused, a reused refresh token revokes the grant, and a flood of registrations or wrong codes is slowed, then refused.

**What would show it is wrong.** A call that reaches a tool with no token, an expired token, a token for another resource or a reused refresh token.
