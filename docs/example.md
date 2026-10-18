# The example

A worked example to try Garrick on before your own work is in it: a week in the work of Robin Hale, product marketing manager at Ashgrove Furniture, an invented maker of office furniture. One employer, five pieces of work across marketing, sales and customers, two call transcripts, and one question Garrick is waiting on you to answer. You stand in for Robin. When you are done, it comes out in one step, and nothing of yours goes with it.

## What is in it

| Piece of work | Where it stands |
|---|---|
| Arc chair launch | The launch email was half written yesterday and stops before its pricing section. Due to Leo and Ines on Friday |
| Larchmont delivery problem | Forty desks arrived damaged. In the call with the customer, two different replacement dates were said, so Garrick asks you which one was promised |
| Westbrook University tender | The sustainability page of the pitch deck is yours to write |
| Dealer price list | Waiting on Nadia in finance to sign off the margins |
| Spring trade show | Booked, and quiet for three weeks |

Things to try: continue the launch email, answer the Larchmont question, or ask "what do I owe people this week?".

Robin's files are in a shared drive, `Ashgrove Shared/`, in the workspace's top folder, a little messy, as shared drives are. Garrick reads them where they are and never writes to them: each piece of work points at its folder there. What you make in the example goes into the example's own record instead.

The dates move with the day you add it, so "yesterday" is always true.

## Add it

To a new workspace, as you install it, from the folder Garrick came in:

```sh
python3 install.py --example
```

Or as a workspace of its own, to look at without installing yours:

```sh
python3 examples/example-work/build.py --target ~/Garrick-example
```

## Remove it, and bring it back

The example lives in a zone of its own, Example, with its own history, so nothing of yours can link into it. From the workspace's top folder:

```sh
python3 System/tools/example.py archive
```

puts the zone, the drive and the example's people in `System/context.md` away in `.archive/Example/`, a folder no history records. Your own zones, people and files are not touched. To bring it back exactly as it was:

```sh
python3 System/tools/example.py restore
```

`python3 System/tools/example.py status` says whether it is there, put away, or never added. To be rid of it for good, archive it and delete `.archive/Example/`.

## Another example

The advisor demo, built by `examples/demo/build.py`, shows what a wall does: two clients who compete, and a carrier who works for both. It is the one to try once your own work has a second party. See [Try it safely](try-it-safely.md).

How the example is built, and how to change its story, is in [its README](../examples/example-work/README.md).
