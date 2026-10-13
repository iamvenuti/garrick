// garrick-sidebar.js: a cmux sidebar for a Garrick workspace (#22).
//
// Each cmux workspace by name, with its unread count, and its tabs under it,
// one line each. A tab titled by a path, or with a title that says only which
// program runs in it (Claude Code, Codex, a shell), shows the last part of its
// folder instead: the thread's name, for a tab desk opened. Each tab's dot is
// blue while its agent is working, orange when it has an unread notification,
// grey otherwise. cmux reports every finished turn as needs_input, so that
// state alone does not colour it. A workspace with a colour in cmux has a bar
// of it before its name: the desk sets a zone's workspace to the colour its
// zone has in the status page's Settings. The zone's icon is not drawn, since
// a sidebar cannot read the file that names it. Click a workspace to select
// it, a tab to focus it. Garrick's mark sits on top; clicking it opens the
// status page.
//
// Install: copy or link this file to ~/.config/cmux/sidebars/garrick.js, then
// `cmux sidebar select garrick`. Right-click the sidebar button to go back to
// cmux's own, which can still drag workspaces into another order.
//
// Written from cmux's published custom-sidebar API (docs/custom-sidebars.md
// in the cmux repository), with nothing from the templates cmux ships. MIT,
// like the rest of Garrick.

// The mark's dark-ground colours (docs/assets/brand.md): the runtime does not
// say whether cmux is light or dark, and its sidebar follows the terminal's
// background, dark by default.
const INK = "#F5F0E6";
const BLUE = "#8EB1F5";
const GREY = "#8A8F98";

// A title that names the program, not the work, after any spinner or symbol
// an agent puts in front of it.
const GENERIC = /^(claude code|claude|codex|zsh|bash|fish|sh|login|terminal)$/i;

function tabName(t) {
  const title = (t.title || "").replace(/^[^A-Za-z0-9~\/]+/, "").trim();
  if (title && !GENERIC.test(title) && title.indexOf("/") < 0 && title.charAt(0) !== "~") return title;
  const folder = (t.directory || "").replace(/\/+$/, "");
  return folder ? folder.slice(folder.lastIndexOf("/") + 1) : title || "Tab";
}

function dot(w, t) {
  const working = (w.agents || []).some((a) => a.panelId === t.id && a.status === "working");
  return working ? BLUE : t.hasUnread ? "orange" : GREY;
}

// The workspace's colour as cmux holds it, for the bar before its name; clear
// when it has none, so every name still starts at the same place.
function swatch(w) {
  return /^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$/.test(w.color || "") ? w.color : "clear";
}

// The workspace root, from the first folder of a tab inside a zone, a wiki or
// System/. The sidebar cannot read files, so the page is opened by its path
// and simply fails to open if it has never been built.
function statusPage(workspaces) {
  for (const w of workspaces || []) {
    for (const d of [w.directory].concat((w.tabs || []).map((t) => t.directory))) {
      const m = /^(\/.*?)\/(Zones|Wikis|System)(\/|$)/.exec(d || "");
      if (m) return "file://" + encodeURI(m[1] + "/System/generated/status.html");
    }
  }
  return null;
}

// The small cut on its 16-point grid, in plain rectangles: the spine, the
// open compartment in blue, the closed one beneath it.
function mark() {
  return HStack({ spacing: 1 }, [
    Rectangle().fill(INK).frame({ width: 5, height: 14 }),
    VStack({ spacing: 1 }, [
      Rectangle().fill(BLUE).frame({ width: 8, height: 6 }),
      Rectangle().fill(INK).frame({ width: 8, height: 7 }),
    ]),
  ]).padding(1);
}

sidebar(() =>
  VStack({ spacing: 4 }, [
    HStack({ spacing: 8 }, [mark(), Text("Garrick").font("headline").color(INK), Spacer()])
      .padding(8)
      .cursor("pointer")
      .onTap(() => {
        const page = statusPage(data.workspaces());
        if (page) openURL(page);
      }),
    Divider(),
    ForEach({ items: () => data.workspaces() ?? [], key: (w) => w.id }, (w) =>
      VStack({ spacing: 1 }, [
        HStack({ spacing: 6 }, [
          Capsule().fill(() => swatch(w())).frame({ width: 4, height: 14 }),
          Text(() => w().title).weight("semibold").lineLimit(1),
          Spacer(),
          Text(() => (w().unread > 0 ? String(w().unread) : "")).font("caption").color("orange"),
        ])
          .padding(6)
          .background(() => (w().selected ? "#FFFFFF14" : null))
          .cornerRadius(6)
          .hoverBackground("#FFFFFF0D")
          .onTap(() => cmux("workspace.select", { workspace_id: w().id })),
        ForEach({ items: () => w().tabs ?? [], key: (t) => t.id }, (t) =>
          HStack({ spacing: 7 }, [
            Circle({ size: 7 }).fill(() => dot(w(), t())),
            Text(() => tabName(t())).lineLimit(1).secondary(),
            Spacer(),
          ])
            .paddingHorizontal(18)
            .paddingVertical(3)
            .hoverBackground("#FFFFFF0D")
            .onTap(() => {
              if (t().surfaceId) cmux("surface.focus", { surface_id: t().surfaceId, workspace_id: w().id });
            })
        ),
      ])
    ),
    Spacer(),
  ])
);
