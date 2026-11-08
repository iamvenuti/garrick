# Context

Who you are and who you deal with. Identity and disambiguation only, never status: where things stand lives in the thread notes, which are kept current. This file loads in every session, so keep it short.

The rows below are examples. Replace them with your own.

## Me

<Your name>. <What you do, and for whom, in a sentence or two.>

My addresses: <you@work.example>, <you@personal.example>. Mail you forward from them is read by who is inside it, not by you.

## Zones

A zone may name one party, which every file in the zone carries; leave it empty for none. New parties says what `scaffold.py party` proposes for a party added in the zone: walled or open.

| Zone | Holds | Party | New parties |
|---|---|---|---|
| Work | <Client work, employer work> | | walled |
| Personal | <Everything that is yours alone> | | walled |

## Parties

Every organisation or person whose confidences you hold. The tag is what project and meeting frontmatter use.

Domains are optional: the part after the @ in their mail addresses. Mail from a listed domain files itself under that party. Personal webmail, such as gmail.com, never names a party by itself.

Walled says whether a party is walled, `yes` or `no`. A walled party's material goes only into work that names that party; an open party's material may go anywhere. The assistant checks this column before it uses a conversation in a project.

| Party | What it is | Zone | Tag | Walled | Domains |
|---|---|---|---|---|---|
| Acme Corp | Client. Supply-chain review | Work | `acme` | yes | acmecorp.example |
| Birch & Co | Client. Market-entry advice; competes with Acme | Work | `birch` | yes | birchco.example |

## People

| Name | Party | Role |
|---|---|---|
| Dana Whitlock | `acme` | Head of procurement; sponsor of the review |
| Theo Marsh | `birch` | Managing partner |

## Aliases

How names arrive by dictation, and what they mean. Add a row whenever the assistant had to ask.

| Heard | Means |
|---|---|
| birch and co, birchen co | Birch & Co |
| dana whitlaw | Dana Whitlock |
