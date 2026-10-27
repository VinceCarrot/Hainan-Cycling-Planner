const DEFAULT_PAGE = "map";
const PAGES = new Set(
  Array.from(document.querySelectorAll(".view[data-view]"), (view) => view.dataset.view),
);
const navLinks = document.querySelectorAll(".sidebar-nav a[data-page]");
const loadedPages = new Set();

function pageFromHash() {
  const match = /^#\/([a-z-]+)/.exec(window.location.hash);
  if (!match) {
    return DEFAULT_PAGE;
  }
  return PAGES.has(match[1]) ? match[1] : "not-found";
}

function showPage(page) {
  for (const view of document.querySelectorAll(".view[data-view]")) {
    view.hidden = view.dataset.view !== page;
  }
  for (const link of navLinks) {
    const active = link.dataset.page === page;
    link.classList.toggle("active", active);
    if (active) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  }

  if (!loadedPages.has(page)) {
    loadedPages.add(page);
    const loader = PAGE_LOADERS[page];
    if (loader) {
      loader();
    }
  }
}

function route() {
  if (!window.location.hash) {
    window.location.replace(`#/${DEFAULT_PAGE}`);
    return;
  }
  showPage(pageFromHash());
}

function renderAttractionCard(attraction, statusLabel, actions) {
  const item = document.createElement("li");
  item.className = "attraction-card";
  item.dataset.id = attraction.id;

  const title = document.createElement("h3");
  title.textContent = attraction.name;

  const details = document.createElement("p");
  details.textContent = `${attraction.region} · ${attraction.category}`;

  const status = document.createElement("span");
  status.className = `status-tag status-${attraction.status}`;
  status.textContent = statusLabel;

  item.append(title, status, details);

  if (attraction.latitude != null && attraction.longitude != null) {
    const coords = document.createElement("p");
    coords.className = "coords";
    coords.textContent = `坐标 ${attraction.latitude}, ${attraction.longitude}（已核实）`;
    item.append(coords);
  } else {
    const coords = document.createElement("p");
    coords.className = "coords coords-missing";
    coords.textContent = "坐标未核实";
    item.append(coords);
  }

  if (attraction.summary?.text) {
    const summary = document.createElement("p");
    summary.className = "claim";
    summary.textContent = attraction.summary.text;
    item.append(summary);
  }

  for (const [label, claims] of [
    ["体验亮点", attraction.highlights],
    ["注意事项", attraction.drawbacks],
  ]) {
    if (!claims?.length) {
      continue;
    }

    const heading = document.createElement("h4");
    heading.textContent = label;
    const claimList = document.createElement("ul");
    claimList.className = "claim-list";

    for (const claim of claims) {
      const entry = document.createElement("li");
      entry.textContent = claim.text;
      claimList.append(entry);
    }

    item.append(heading, claimList);
  }

  const sources = document.createElement("ul");
  sources.className = "source-list";
  for (const source of attraction.sources) {
    const entry = document.createElement("li");
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = `${source.platform} · ${source.title}`;
    entry.append(link);

    if (source.published_at) {
      const date = document.createElement("span");
      date.textContent = ` (${source.published_at})`;
      entry.append(date);
    }

    sources.append(entry);
  }

  if (sources.childElementCount) {
    const sourceHeading = document.createElement("h4");
    sourceHeading.textContent = "资料来源";
    item.append(sourceHeading, sources);
  }

  const imageNote = attraction.images.find((image) => !image.local_path);
  if (imageNote) {
    const note = document.createElement("p");
    note.className = "image-note";
    note.textContent = "有开放许可图片来源记录；本地图片文件尚未缓存，离线时不可见。";
    item.append(note);
  }

  if (actions?.length) {
    const bar = document.createElement("div");
    bar.className = "card-actions";
    for (const action of actions) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `button button-small ${action.className}`;
      button.textContent = action.label;
      button.addEventListener("click", () => action.onClick(attraction, item));
      bar.append(button);
    }
    item.append(bar);
  }

  return item;
}

function showReviewFeedback(text) {
  const feedback = document.querySelector("#review-feedback");
  feedback.textContent = text;
  feedback.hidden = !text;
}

function refreshReviewCounts(remaining) {
  document.querySelector("#review-count").textContent = `${remaining} 个待审核候选`;
  const message = document.querySelector("#review-message");
  message.hidden = remaining > 0;
  message.textContent = remaining ? "" : "暂无候选景点。新增资料会保留来源，并标明待核实内容。";
  const badge = document.querySelector("#nav-review-count");
  badge.textContent = String(remaining);
  badge.hidden = remaining === 0;
  // The library must reload the next time it is opened.
  loadedPages.delete("library");
}

async function runReviewAction(attraction, card, request, successText) {
  card.classList.add("is-busy");
  showReviewFeedback("");
  try {
    const response = await fetch(request.url, {
      method: request.method,
      headers: request.body ? { "Content-Type": "application/json" } : undefined,
      body: request.body ? JSON.stringify(request.body) : undefined,
    });
    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const payload = await response.json();
        if (payload?.error) {
          detail = payload.error;
        }
      } catch {
        // Keep the HTTP status as the error detail.
      }
      throw new Error(detail);
    }
    card.remove();
    refreshReviewCounts(document.querySelectorAll("#review-list .attraction-card").length);
    showReviewFeedback(successText);
  } catch (error) {
    card.classList.remove("is-busy");
    showReviewFeedback(
      `操作失败：${error instanceof Error ? error.message : "未知错误"}`,
    );
  }
}

const REVIEW_ACTIONS = [
  {
    label: "通过审核",
    className: "button-approve",
    onClick: (attraction, card) =>
      runReviewAction(
        attraction,
        card,
        {
          url: `/api/attractions/${encodeURIComponent(attraction.id)}/status`,
          method: "POST",
          body: { status: "approved" },
        },
        `「${attraction.name}」已通过审核，并已加入景点库。`,
      ),
  },
  {
    label: "删除",
    className: "button-danger",
    onClick: (attraction, card) => {
      const confirmed = window.confirm(
        `确定删除「${attraction.name}」？\n该记录及其来源资料会从 attractions.json 中永久移除，无法撤销。`,
      );
      if (!confirmed) {
        return;
      }
      runReviewAction(
        attraction,
        card,
        {
          url: `/api/attractions/${encodeURIComponent(attraction.id)}`,
          method: "DELETE",
        },
        `「${attraction.name}」已从目录中删除。`,
      );
    },
  },
];

async function loadAttractionList({
  status,
  statusLabel,
  prefix,
  countText,
  emptyText,
  actions,
  onLoaded,
}) {
  const count = document.querySelector(`#${prefix}-count`);
  const message = document.querySelector(`#${prefix}-message`);
  const list = document.querySelector(`#${prefix}-list`);

  try {
    const response = await fetch(`/api/attractions?status=${encodeURIComponent(status)}`);
    if (!response.ok) {
      throw new Error(`景点库读取失败（HTTP ${response.status}）`);
    }

    const attractions = await response.json();
    count.textContent = countText(attractions.length);
    message.hidden = attractions.length > 0;
    message.textContent = attractions.length ? "" : emptyText;

    list.replaceChildren(
      ...attractions.map((attraction) =>
        renderAttractionCard(attraction, statusLabel, actions),
      ),
    );
    onLoaded?.(attractions);
  } catch (error) {
    count.textContent = "读取失败";
    message.hidden = false;
    message.textContent = error instanceof Error ? error.message : "景点库读取失败";
  }
}

const PAGE_LOADERS = {
  library: () =>
    loadAttractionList({
      status: "approved",
      statusLabel: "已审核",
      prefix: "library",
      countText: (n) => `${n} 个已审核景点`,
      emptyText: "还没有已审核的景点。请在“待审核景点”中完成审核后，批准的景点会出现在这里。",
    }),
  review: () =>
    loadAttractionList({
      status: "candidate",
      statusLabel: "待审核",
      prefix: "review",
      countText: (n) => `${n} 个待审核候选`,
      emptyText: "暂无候选景点。新增资料会保留来源，并标明待核实内容。",
      actions: REVIEW_ACTIONS,
    }),
};

async function loadReviewBadge() {
  const badge = document.querySelector("#nav-review-count");
  try {
    const response = await fetch("/api/attractions?status=candidate");
    if (!response.ok) {
      return;
    }
    const attractions = await response.json();
    if (attractions.length) {
      badge.textContent = String(attractions.length);
      badge.hidden = false;
    }
  } catch {
    // The badge is informational only; the review page reports errors itself.
  }
}

window.addEventListener("hashchange", route);
route();
loadReviewBadge();
