# Extra: phone access

Use your phone to ask about the Garrick files on your computer. For example, before a call while away from home, ask “Open Supplier Review, Next Call. What do I owe them? Answer briefly; do not change anything.” Include the project so the assistant knows which party's work the answer is for.

Set up and test the desk workflow first. Remote access belongs to the assistant provider; Garrick does not install or enable it.

## Codex and remote voice on iPhone

The documented consumer setup uses the ChatGPT desktop app as the host. Install it even if you normally use Codex CLI in a terminal or cmux. Add your existing Garrick folder as a local project in the app. The files and resume notes carry across; a CLI chat need not appear there.

In the desktop app, open **Settings > Connections > Control this Mac or PC** and follow **Set up** or **Add**. Scan its QR code with your iPhone and complete pairing in ChatGPT using the same account and workspace. On the phone, choose **Codex** (or **Remote** in versions using that label), the host and your Garrick project. See [Remote connections](https://learn.chatgpt.com/docs/remote-connections).

ChatGPT Voice supports Remote on iOS after pairing. Use the voice-chat control when available; access depends on plan, rollout and workspace settings. See [Voice](https://learn.chatgpt.com/docs/features/voice). Ordinary ChatGPT voice outside the connected host's task does not, by itself, open the files on your laptop.

Leave the host app running and the computer awake, online and preferably plugged in. Sleeping, closing the app or losing the network interrupts access. On a laptop, test the power and lid arrangement before relying on it away from home.

## Claude Code from a terminal or desktop

Claude Code Remote Control can connect a local terminal session to Claude on your phone, without installing the Claude desktop app. In a signed-in session opened on your Garrick workspace, run `/remote-control` and follow the displayed link or QR code. In Claude Desktop's local Code session, the same command is available. Eligibility depends on the account and organization settings. Follow [Claude Code Remote Control](https://code.claude.com/docs/en/remote-control).

Keep the computer and the local session running. Use typing or mobile dictation for prompts; do not assume that remote access also supplies the same live voice experience as Codex.

## Test before leaving home

1. On the computer, wrap a thread with a recognisable next action.
2. On the phone, use mobile data to connect to the host and ask to open that project and thread. Confirm it reads the saved note.
3. If using voice, check that you can speak and hear the answer. Otherwise use text.
4. Check where approvals appear and that the host remains reachable with the power arrangement you intend to leave it in.

Remote access uses the host's files, tools and permissions. It adds no new confidentiality boundary. The assistant still has to apply Garrick's rules, and the [commit check has the same limits](../principles.md#what-the-check-covers). Browse your own record freely, but name the destination project whenever asking for material for someone else.

## What you lose without it

Only access from the phone. The desktop and terminal routes work independently of it. Obsidian on a phone is a separate way to read synced notes; it does not provide a remote assistant session.

Provider guidance checked on 1 October 2026. Follow the linked documentation for current availability and setup labels.
