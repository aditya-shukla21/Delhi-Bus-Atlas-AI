"use strict";

const byId = (id) => document.getElementById(id);
const fields = ["origin", "destination"];
const selected = { origin: null, destination: null };
const levels = new Map([["Low", "▂"], ["Medium", "▄"], ["High", "▆"], ["Very High", "█"], ["Unknown", "?"]]);
const hindiLevels = {Low: "कम", Medium: "मध्यम", High: "अधिक", "Very High": "बहुत अधिक", Unknown: "अज्ञात"};
let lang = "en";
let currentPlan = null;
let currentAdvice = null;
let activeMap = 0;
let questionVersion = 0;
let adviceVersion = 0;
let sliderTimer;
let lastQuestion = "";
const queryCache = new Map();
const t = (english, hindi) => lang === "hi" ? hindi : english;
const renderLevel = (level) => t(levelName(level), hindiLevels[levelName(level)]);
const levelClass = (level) => levelName(level).toLowerCase().replace(" ", "-");
const minuteText = (n) => t(n + " min", n + " मिनट");
const errorText = (error) => t(error.message, "स्थानीय डेटा नहीं खुल सका। कृपया फिर से प्रयास करें।");
let planVersion = 0;
let operatorVersion = 0;
let formTouched = false;

function el(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.textContent = value;
  return node;
}

async function api(path, params = {}) {
  const key = path + "?" + new URLSearchParams(Object.entries(params).sort());
  if (queryCache.has(key)) return queryCache.get(key);
  async function request() {
    if (path === "/v1/ask" && window.JourneyAI) return window.JourneyAI.answer(params, api);
    if (window.busAtlasApi) return window.busAtlasApi(path, params);
    const url = new URL(path, location.origin);
    url.search = new URLSearchParams(params);
    const response = await fetch(url);
    if (!response.ok) throw new Error("The local planner could not complete this request. Please try again.");
    return response.json();
  }
  const response = request();
  if (queryCache.size >= 40) queryCache.delete(queryCache.keys().next().value);
  queryCache.set(key, response);
  try { return await response; } catch (error) { queryCache.delete(key); throw error; }
}

function chooseStop(field, stop) {
  selected[field] = stop;
  byId(field).value = stop?.name ?? "";
}

function resetResults() {
  formTouched = true;
  planVersion += 1;
  adviceVersion++;
  questionVersion++;
  currentPlan = null;
  currentAdvice = null;
  lastQuestion = "";
  clearTimeout(sliderTimer);
  byId("journey-tools").hidden = true;
  byId("answer").textContent = "";
  document.querySelector(".results").setAttribute("aria-busy", "false");
  byId("result-context").textContent = t("Select Find journeys to update the options.", "यात्राएँ देखने के लिए ‘यात्राएँ खोजें’ चुनें।");
  byId("options").replaceChildren();
  byId("form-message").textContent = "";
}

function attachStopSearch(field) {
  const input = byId(field);
  const list = byId(field + "-list");
  let version = 0;
  let timer;
  let items = [];
  let active = -1;

  function close() {
    version += 1;
    clearTimeout(timer);
    items = [];
    active = -1;
    list.replaceChildren();
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function pick(index) {
    if (!items[index]) return;
    chooseStop(field, items[index]);
    byId("form-message").textContent = "";
    close();
  }

  function selectIndex(index) {
    active = index;
    Array.from(list.children).forEach((item, i) => item.setAttribute("aria-selected", String(i === index)));
    const option = list.children[index];
    input.setAttribute("aria-activedescendant", option.id);
    option.scrollIntoView({ block: "nearest" });
  }

  input.addEventListener("input", () => {
    resetResults();
    selected[field] = null;
    close();
    const q = input.value.trim();
    if (!q) return;
    const requestId = version;
    timer = setTimeout(async () => {
      try {
        const stops = await api("/v1/stops/search", { q });
        if (requestId !== version || document.activeElement !== input) return;
        items = stops;
        if (!stops.length) {
          byId("form-message").textContent = t("No matching stops. Try a shorter name.", "कोई स्टॉप नहीं मिला। अंग्रेज़ी में नाम का छोटा हिस्सा लिखें।");
          return;
        }
        stops.forEach((stop, index) => {
          const row = el("li");
          row.setAttribute("role", "option");
          row.setAttribute("aria-selected", "false");
          row.id = field + "-option-" + index;
          row.append(el("span", "", stop.name), el("small", "", "#" + stop.id));
          row.addEventListener("pointerdown", (event) => event.preventDefault());
          row.addEventListener("click", () => pick(index));
          list.append(row);
        });
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
      } catch (error) {
        if (version === requestId) byId("form-message").textContent = errorText(error);
      }
    }, 130);
  });
  input.addEventListener("blur", close);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { close(); return; }
    if (!items.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = event.key === "ArrowDown" ? active + 1 : active < 0 ? items.length - 1 : active - 1;
      selectIndex((next + items.length) % items.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      pick(active < 0 ? 0 : active);
    }
  });
}

function levelName(value) { return levels.has(value) ? value : "Unknown"; }
function count(number, single, plural = single + "s") {
  const hindi = {ticket:"टिकट",date:"दिन",stretch:"खंड",transfer:"बदलाव",journey:"यात्राएँ"};
  return number + " " + t(number === 1 ? single : plural, hindi[single] || single);
}
function badge(value) {
  const name = levelName(value);
  const pill = el("span", "crowd-badge " + levelClass(name));
  const icon = el("span", "", levels.get(name));
  icon.setAttribute("aria-hidden", "true");
  pill.append(icon, document.createTextNode(t(name === "Unknown" ? "Crowding unknown" : name + " crowding", "भीड़ " + renderLevel(name))));
  return pill;
}

function segmentList(leg) {
  const detail = el("section", "leg");
  detail.append(el("h4", "", leg.route + " · " + leg.origin + " → " + leg.destination));
  const timing = [leg.departure + "–" + leg.arrival, count(leg.stops, "stretch", "stretches")];
  if (leg.headsign) timing.push(t("Towards " + leg.headsign, leg.headsign + " की ओर"));
  detail.append(el("p", "", timing.join(" · ")));
  const list = el("ol");
  for (const segment of leg.segments) {
    const level = levelName(segment.level);
    const row = el("li");
    row.append(el("i", "swatch " + levelClass(level)),
      el("strong", "", segment.from_name + " → " + segment.to_name));
    const support = level === "Unknown" || segment.load == null
      ? t("Unknown · Insufficient ticket evidence for this stretch.", "अज्ञात · इस खंड के लिए पर्याप्त टिकट डेटा उपलब्ध नहीं है।")
      : renderLevel(level) + " · " + Number(segment.load).toFixed(2) + t(" predicted ticketed passengers per scheduled bus · ", " अनुमानित टिकटधारी यात्री प्रति निर्धारित बस · ") +
        count(segment.tickets, "ticket") + " / " + count(segment.days, "date");
    row.append(el("p", "", support));
    list.append(row);
  }
  detail.append(list);
  return detail;
}

function journeyCard(option) {
  const card = el("article", "journey");
  const body = el("div", "card-main");
  const line = el("div", "card-line");
  for (const leg of option.legs) line.append(el("span", "route-tag", leg.route));
  line.append(el("span", "transfer-tag", option.transfers ? count(option.transfers, "transfer") : t("Direct", "सीधी बस")),
    badge(option.level));
  const times = el("div", "times");
  const heading = el("h3");
  heading.append(document.createTextNode(option.departure + " "), el("span", "arrow", "→"),
    document.createTextNode(" " + option.arrival));
  const duration = el("p", "", t(option.duration_min + " min total", "कुल " + minuteText(option.duration_min)));
  duration.append(el("span", "", " · " + minuteText(option.wait_min) + t(" wait", " प्रतीक्षा")));
  times.append(heading, duration);
  const names = [option.legs[0].origin, ...option.legs.map((leg) => leg.destination)];
  const segments = option.legs.flatMap((leg) => leg.segments);
  const strip = el("div", "strip");
  strip.setAttribute("aria-hidden", "true");
  for (const segment of segments) {
    const level = levelName(segment.level);
    const bar = el("i", levelClass(level));
    bar.title = segment.from_name + " → " + segment.to_name + " · " + renderLevel(level);
    strip.append(bar);
  }
  const coverage = Math.round(option.coverage * 100);
  body.append(line, times, el("p", "stops-text", names.join(" → ")), strip,
    el("p", "strip-caption", count(segments.length, "stretch", "stretches") + " · " +
      t("Crowd evidence for " + coverage + "% of ride time", "बस में बिताए समय के " + coverage + "% पर भीड़ का डेटा")));
  const details = el("details");
  details.append(el("summary", "", t("Stops & crowd evidence", "स्टॉप और भीड़ का आधार")));
  details.addEventListener("toggle", () => {
    if (details.open && details.children.length === 1) {
      for (const leg of option.legs) details.append(segmentList(leg));
    }
  });
  card.append(body, details);
  return card;
}

function queryParams() {
  return {from: selected.origin.id, to: selected.destination.id, date: byId("date").value,
    time: byId("time").value, preference: byId("comfort").value};
}

function drawMap() {
  if (!currentPlan?.options.length || byId("planner-view").hidden || byId("journey-tools").hidden) return;
  const option = currentPlan.options[activeMap];
  const canvas = byId("journey-map");
  const width = Math.floor(canvas.getBoundingClientRect().width);
  if (width < 10) return;
  const height = 218;
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * ratio);
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(ratio, ratio);
  const legs = option.legs.map(leg => ({...leg, points: (leg.geometry?.points || []).filter(
    point => Array.isArray(point) && point.length === 2 && point.every(Number.isFinite))}));
  const all = legs.flatMap(leg => leg.points);
  const info = byId("map-info");
  if (!all.length) {
    info.textContent = t("No geographic coordinates for this journey.", "इस यात्रा के लिए भौगोलिक निर्देशांक उपलब्ध नहीं हैं।");
    canvas.setAttribute("aria-label", info.textContent);
    return;
  }
  const lats = all.map(p => p[0]), lons = all.map(p => p[1]);
  const midLat = (Math.min(...lats) + Math.max(...lats)) / 2;
  const midLon = (Math.min(...lons) + Math.max(...lons)) / 2;
  const kmLat = 111.2;
  const kmLon = kmLat * Math.cos(midLat * Math.PI / 180);
  const scale = Math.min((width - 78) / Math.max(.12,(Math.max(...lons)-Math.min(...lons))*kmLon),
    (height-60) / Math.max(.12,(Math.max(...lats)-Math.min(...lats))*kmLat));
  const xy = ([lat, lon]) => [width / 2 + (lon - midLon) * kmLon * scale, height / 2 - (lat - midLat)*kmLat*scale];
  const palette = ["#155f58","#a55130"];
  ctx.lineJoin = "round"; ctx.lineCap = "round";
  legs.forEach((leg, i) => {
    if (!leg.points.length) return;
    const path = new Path2D();
    leg.points.forEach((p,j) => { const pos = xy(p); if (j === 0) path.moveTo(...pos); else path.lineTo(...pos); });
    ctx.strokeStyle = "#fffdf7"; ctx.lineWidth = 8; ctx.stroke(path);
    ctx.strokeStyle = palette[i % palette.length]; ctx.lineWidth = 4;
    ctx.setLineDash(leg.geometry?.source === "stop_chain" ? [5,4] : []);
    ctx.stroke(path); ctx.setLineDash([]);
  });
  function marker(p, letter, colour) {
    const [x,y] = xy(p);
    ctx.beginPath(); ctx.arc(x,y,10,0,2*Math.PI); ctx.fillStyle = colour; ctx.fill();
    ctx.strokeStyle = "#fffdf7"; ctx.lineWidth = 2; ctx.stroke();
    ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.font = "bold 11px sans-serif";
    ctx.fillStyle = "#fff"; ctx.fillText(letter,x,y);
  }
  marker(all[0],"A","#143f36");
  if (legs.length > 1 && legs[1].points.length) marker(legs[1].points[0],"•","#92532d");
  marker(all[all.length-1],"B","#143f36");
  ctx.textAlign = "left"; ctx.textBaseline = "alphabetic"; ctx.fillStyle = "#3e584c"; ctx.font = "12px sans-serif";
  ctx.fillText(t("↑ N","↑ उत्तर"),12,18);
  const scaleKm = [0.02,0.05,0.1,0.2,0.5,1,2,5,10].filter(val => val * scale <= Math.min(85,width/3)).pop();
  if (scaleKm) {
    const y = height - 12, x = 14;
    ctx.fillRect(x,y,scaleKm*scale,2);
    ctx.fillText(scaleKm >= 1 ? scaleKm + t(" km"," किमी") : Math.round(scaleKm*1000)+t(" m"," मी"),x,y-4);
  }
  const endpoints = "A · " + option.legs[0].origin + "　 B · " + option.legs.at(-1).destination;
  const source = legs.some(leg => leg.geometry?.source === "stop_chain") ?
    t("Dashed stretches connect scheduled stops.", "टूटी रेखाएँ निर्धारित स्टॉप जोड़ती हैं।") :
    t("Line follows the scheduled GTFS route shape.", "रेखा GTFS के निर्धारित रूट को दिखाती है।");
  info.textContent = endpoints + " · " + source;
  canvas.setAttribute("aria-label", info.textContent);
}

function renderPlan() {
  if (!currentPlan) return;
  const options = currentPlan.options;
  const preference = Number(byId("comfort").value);
  const label = preference === 0 ? t("Fastest first","सबसे तेज़ पहले") :
    preference === 100 ? t("Least crowded first","सबसे कम भीड़ पहले") : t("Comfort " + preference + "%","आराम को " + preference + "% प्राथमिकता");
  byId("result-context").textContent = count(options.length,"journey","journeys") + " · " + byId("time").value + " IST · " + label;
  byId("options").replaceChildren(...options.map(journeyCard));
  byId("journey-tools").hidden = options.length === 0;
  if (!options.length) {
    byId("options").append(el("p","empty",t(currentPlan.message || "No journeys found. Try another stop or time.",
      "अगले एक घंटे में कोई सीधी या एक बदलाव वाली यात्रा नहीं मिली। स्टॉप की दिशा, तारीख या समय बदलकर देखें।")));
    return;
  }
  const select = byId("map-option");
  select.replaceChildren(...options.map((option,i) => {
    const entry = el("option","",option.legs.map(leg=>leg.route).join(" → ") + " · " + option.departure);
    entry.value = String(i);
    return entry;
  }));
  select.value = String(activeMap);
  drawMap();
}

function summaryText(summary) {
  if (!summary) return t("No later bus", "बाद की बस नहीं मिली");
  return summary.routes.join(" → ") + " · " + summary.departure + "–" + summary.arrival +
    " · " + renderLevel(summary.level) + t(" crowding", " भीड़") + " · " +
    Math.round(summary.coverage * 100) + t("% ride coverage","% यात्रा समय का डेटा");
}

function renderAdvice() {
  if (!currentAdvice) return;
  const data = currentAdvice;
  const recommendation = data.recommendation;
  const alternatives = byId("advice-details");
  alternatives.replaceChildren();
  if (recommendation?.alternative) {
    const delta = recommendation.arrival_delta_min;
    const difference = delta === 0 ? t("same arrival time","पहुँचने का समय समान") :
      minuteText(Math.abs(delta)) + (delta > 0 ? t(" later arrival"," देर से पहुँचें") : t(" earlier arrival"," पहले पहुँचें"));
    byId("advice").textContent = t("Try leaving at ", "प्रस्थान के लिए ") + recommendation.time +
      t(" IST. ", " IST चुनें। ") + summaryText(recommendation.alternative) + " · " + difference + t(".", "।");
  } else {
    byId("advice").textContent = t("No later departure met the crowding and arrival-time criteria.",
      "बाद की किसी बस में भीड़ और पहुँचने के समय की दोनों शर्तें पूरी नहीं हुईं।");
  }
  if (data.baseline) alternatives.append(el("p","advice-baseline",t("Current choice · ","वर्तमान विकल्प · ") + summaryText(data.baseline)));
  if (!data.windows?.length) return;
  const details = el("details","advice-windows");
  details.append(el("summary","",t("Compare departure windows","प्रस्थान समय की तुलना करें")));
  details.append(el("p","",t("A recommendation needs a lower crowd band, ticket evidence for at least 75% of both rides and arrival within 15 minutes of the original option.",
    "सुझाव के लिए भीड़ का स्तर कम होना चाहिए, दोनों यात्राओं के कम से कम 75% समय का टिकट डेटा चाहिए और बस मूल विकल्प से अधिकतम 15 मिनट देर से पहुँचे।")));
  const list = el("ul");
  for (const window of data.windows) {
    const item = el("li");
    item.append(el("strong","",window.time+" IST"),el("span","",summaryText(window.alternative)));
    list.append(item);
  }
  details.append(list);
  alternatives.append(details);
}

async function loadAdvice() {
  const version = ++adviceVersion;
  currentAdvice = null;
  byId("advice").textContent = t("Comparing later departures…","बाद के प्रस्थान की तुलना हो रही है…");
  byId("advice-details").replaceChildren();
  try {
    const data = await api("/v1/advice",queryParams());
    if (version !== adviceVersion) return;
    currentAdvice = data;
    renderAdvice();
  } catch (error) { if (version === adviceVersion) byId("advice").textContent = errorText(error); }
}

async function askQuestion() {
  const q = byId("question").value.trim();
  if (!q || !currentPlan?.options.length) return;
  const version = ++questionVersion;
  lastQuestion = q;
  byId("answer").textContent = t("Checking your journey options…","आपकी यात्रा के विकल्प जाँचे जा रहे हैं…");
  try {
    const result = await api("/v1/ask",{...queryParams(),q,lang});
    if (version === questionVersion) byId("answer").textContent = result.answer;
  } catch (error) { if (version === questionVersion) byId("answer").textContent = errorText(error); }
}

async function showJourneys() {
  const version = ++planVersion;
  const results = document.querySelector(".results");
  byId("form-message").textContent = "";
  for (const field of fields) {
    if (!selected[field]) {
      byId("form-message").textContent = t("Choose a matching " + field + " stop from the list.",
        field === "origin" ? "सूची से प्रस्थान स्टॉप चुनें।" : "सूची से गंतव्य स्टॉप चुनें।");
      byId(field).focus(); return;
    }
  }
  if (selected.origin.id === selected.destination.id) {
    byId("form-message").textContent = t("Choose different origin and destination stops.", "प्रस्थान और गंतव्य के लिए अलग स्टॉप चुनें।"); return;
  }
  if (!byId("trip-form").reportValidity()) return;
  adviceVersion++; questionVersion++;
  currentPlan = null; currentAdvice = null; lastQuestion = "";
  byId("answer").textContent = "";
  results.setAttribute("aria-busy","true");
  byId("result-context").textContent = t("Finding scheduled journeys…","निर्धारित यात्राएँ खोजी जा रही हैं…");
  byId("options").replaceChildren(); byId("journey-tools").hidden = true;
  try {
    const data = await api("/v1/plan",queryParams());
    if (version !== planVersion) return;
    currentPlan = data; activeMap = 0;
    renderPlan();
    if (data.options.length) loadAdvice();
  } catch (error) {
    if (version !== planVersion) return;
    byId("result-context").textContent = t("Unable to load journey options.","यात्रा के विकल्प नहीं खुल सके।");
    byId("options").replaceChildren(el("p","empty",errorText(error)));
  } finally {
    if (version === planVersion) results.setAttribute("aria-busy","false");
  }
}

async function showHotspots() {
  const version = ++operatorVersion;
  const day = byId("day-type").value;
  const bin = byId("hour").value;
  const period = byId("hour").selectedOptions[0].textContent + " IST";
  byId("operator-context").textContent = t("Finding historical load estimates…","पिछले यात्रा भार का अनुमान खोजा जा रहा है…");
  byId("hotspots").replaceChildren();
  try {
    const rows = await api("/v1/hotspots", { day, bin });
    if (version !== operatorVersion) return;
    byId("operator-context").textContent = t("Highest predicted load per scheduled bus · One stretch per directional route", "प्रति निर्धारित बस सबसे अधिक अनुमानित यात्री · हर दिशा के रूट से एक खंड") + " · " + period;
    if (!rows.length) {
      byId("hotspots").append(el("p", "empty", t("No stretches meet the evidence threshold for this half-hour and day type.","चुने गए आधे घंटे और दिन के प्रकार में किसी खंड के लिए पर्याप्त डेटा नहीं है।")));
      return;
    }
    const wrap = el("div", "table-wrap");
    const table = el("table");
    table.append(el("caption", "sr-only", t("Predicted ticketed passengers by route and stretch", "रूट और खंड के अनुसार अनुमानित टिकटधारी यात्री") + " · " + byId("day-type").selectedOptions[0].textContent + " · " + period));
    const head = table.createTHead().insertRow();
    for (const name of [t("Route","रूट"), t("Stretch","खंड"), t("Predicted ticketed passengers per scheduled bus","प्रति निर्धारित बस अनुमानित टिकटधारी यात्री"), t("Evidence","डेटा का आधार")]) {
      const th = el("th", "", name);
      th.scope = "col";
      head.append(th);
    }
    const body = table.createTBody();
    for (const item of rows) {
      const row = body.insertRow();
      row.insertCell().append(el("span", "route-tag", item.route));
      row.insertCell().textContent = item.from_name + " → " + item.to_name;
      const published = item.level !== "Unknown" && Number.isFinite(item.load);
      row.insertCell().append(el("strong", "", published ? item.load.toFixed(2) : renderLevel("Unknown")),
        el("small", "", published ? renderLevel(item.level) : ""));
      const evidence = row.insertCell();
      if (published) evidence.append(document.createTextNode(count(item.tickets, "ticket")), el("small", "", count(item.days, "date")));
      else evidence.textContent = t("Insufficient evidence", "अपर्याप्त डेटा");
    }
    wrap.append(table);
    byId("hotspots").append(wrap);
  } catch (error) {
    if (version === operatorVersion) byId("operator-context").textContent = errorText(error);
  }
}

function setView() {
  const operator = location.hash === "#operator";
  byId("planner-view").hidden = operator;
  byId("operator-view").hidden = !operator;
  byId("nav-planner").removeAttribute("aria-current");
  byId("nav-operator").removeAttribute("aria-current");
  byId(operator ? "nav-operator" : "nav-planner").setAttribute("aria-current", "page");
  const heading = operator ? t("Explore Delhi bus loads","दिल्ली बसों में भीड़ देखें") : t("Plan your bus journey","अपनी बस यात्रा चुनें");
  byId("page-title").replaceChildren(document.createTextNode(heading), el("span", "", t(".", "।")));
  byId("page-description").textContent = operator ? t("Find the stretches with the most predicted ticketed passengers per scheduled bus in a half-hour window.","चुने गए आधे घंटे में वे खंड देखें जहाँ प्रति निर्धारित बस सबसे अधिक टिकटधारी यात्रियों का अनुमान है।") :
    t("Compare travel time and expected crowding on Delhi buses.","दिल्ली की बसों में यात्रा का समय और अनुमानित भीड़ एक साथ देखें।");
  document.title = t("Delhi Bus Atlas","दिल्ली बस एटलस") + " · " + (operator ? t("Operator view","संचालक दृश्य") : t("Journey planner","यात्रा योजनाकार"));
  if (operator) showHotspots();
  else drawMap();
}

const staticHindi = {
  "Delhi Bus Atlas": "दिल्ली बस एटलस", "Journey planner": "यात्रा योजनाकार", "Operator view": "संचालक दृश्य",
  "Skip to planner": "यात्रा योजनाकार पर जाएँ", "Journey details": "यात्रा का विवरण", "Example journey": "उदाहरण यात्रा",
  "Saved from the October model. Open the full planner to change the stops or departure.": "अक्टूबर मॉडल की सहेजी गई यात्रा। स्टॉप या प्रस्थान बदलने के लिए पूरा योजनाकार खोलें।",
  "From": "कहाँ से", "To": "कहाँ तक", "Date": "तारीख", "Leave at": "प्रस्थान", "Find journeys": "यात्राएँ खोजें",
  "Comfort preference": "आराम की प्राथमिकता", "Fastest": "सबसे तेज़", "Least crowded": "सबसे कम भीड़",
  "Reading the crowd estimate": "भीड़ के अनुमान को समझें",
  "Each strip compares the predicted number of ticketed passengers crossing a stretch per scheduled bus with October levels across Delhi. Unknown means too little evidence. Seat availability is unmeasured.": "हर पट्टी बताती है कि दो स्टॉप के बीच प्रति निर्धारित बस अनुमानित टिकटधारी यात्रियों की संख्या दिल्ली के अक्टूबर के आँकड़ों की तुलना में कितनी है। ‘अज्ञात’ का अर्थ है कि पर्याप्त डेटा नहीं है। सीट उपलब्धता का अनुमान नहीं लगाया गया है।",
  ...hindiLevels, "Journey options": "यात्रा के विकल्प", "Route map":"रूट का नक्शा", "Mapped journey":"नक्शे पर दिखाई गई यात्रा",
  "Leave later?": "बाद में निकलें?", "Ask about your journey": "अपनी यात्रा के बारे में पूछें", "Journey question": "यात्रा से जुड़ा सवाल", "Ask": "पूछें",
  "Higher-load stretches": "अधिक भीड़ वाले खंड", "Stretches need at least 10 supporting ticket crossings across 3 distinct dates.": "हर खंड के लिए कम से कम 3 अलग-अलग दिनों के ऐसे 10 टिकट चाहिए जिनकी यात्रा उस खंड से गुज़री हो।",
  "Day type": "दिन का प्रकार", "Weekday": "सोमवार–शुक्रवार", "Saturday": "शनिवार", "Sunday": "रविवार", "Half-hour window": "आधे घंटे का अंतराल",
  "Historical ticket estimates · Scheduled bus times · Delhi, IST": "पुराने टिकटों पर आधारित अनुमान · निर्धारित बस समय · दिल्ली, भारतीय मानक समय",
  "Views":"दृश्य", "Delhi Bus Atlas home":"दिल्ली बस एटलस मुख्य पृष्ठ", "Search origin stop":"प्रस्थान स्टॉप अंग्रेज़ी में खोजें", "Search destination stop":"गंतव्य स्टॉप अंग्रेज़ी में खोजें",
  "Origin stops":"प्रस्थान स्टॉप", "Destination stops":"गंतव्य स्टॉप", "Swap stops":"स्टॉप अदलें", "Swap origin and destination":"प्रस्थान और गंतव्य अदलें",
  "Crowd levels":"भीड़ के स्तर", "Which option is less crowded?":"किस विकल्प में भीड़ कम है?"
};

function setupLanguage() {
  const bindings = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const original = node.nodeValue;
    const english = original.trim();
    if (!staticHindi[english]) continue;
    bindings.push(() => { node.nodeValue = original.replace(english,t(english,staticHindi[english])); });
  }
  for (const element of document.querySelectorAll("[aria-label],[title],[placeholder]")) {
    for (const attr of ["aria-label","title","placeholder"]) {
      const english = element.getAttribute(attr);
      if (english && staticHindi[english]) bindings.push(() => element.setAttribute(attr,t(english,staticHindi[english])));
    }
  }
  byId("language").addEventListener("click", () => {
    lang = lang === "en" ? "hi" : "en";
    document.documentElement.lang = lang;
    for (const apply of bindings) apply();
    const button = byId("language");
    button.textContent = t("हिन्दी","English");
    button.lang = t("hi","en");
    button.setAttribute("aria-label",t("हिन्दी में देखें","Switch to English"));
    byId("form-message").textContent = "";
    updateSlider();
    setView();
    if (currentPlan) renderPlan();
    else byId("result-context").textContent = t("Choose stops to compare journeys.","यात्राओं की तुलना के लिए स्टॉप चुनें।");
    if (currentAdvice) renderAdvice();
    if (lastQuestion) askQuestion();
  });
}

function updateSlider() {
  const control = byId("comfort");
  byId("comfort-value").value = control.value + "%";
  control.setAttribute("aria-valuetext", control.value + t("% comfort priority", "% आराम की प्राथमिकता"));
}

async function initialize() {
  setupLanguage();
  fields.forEach(attachStopSearch);
  function halfHourClock(bin) {
    return String(Math.floor(bin / 2) % 24).padStart(2, "0") + (bin % 2 ? ":30" : ":00");
  }
  for (let bin = 0; bin < 48; bin++) {
    const option = el("option", "", halfHourClock(bin) + "–" + halfHourClock(bin + 1));
    option.value = String(bin);
    byId("hour").append(option);
  }
  byId("hour").value = "18";
  byId("operator-form").addEventListener("change", showHotspots);
  byId("operator-form").addEventListener("submit", (event) => { event.preventDefault(); showHotspots(); });
  byId("trip-form").addEventListener("submit", (event) => { event.preventDefault(); formTouched = true; showJourneys(); });
  byId("swap").addEventListener("click", () => {
    const origin = selected.origin;
    chooseStop("origin", selected.destination);
    chooseStop("destination", origin);
    resetResults();
  });
  for (const id of ["date", "time"]) byId(id).addEventListener("input", resetResults);
  updateSlider();
  byId("comfort").addEventListener("input", () => {
    updateSlider();
    clearTimeout(sliderTimer);
    if (selected.origin && selected.destination && byId("trip-form").checkValidity()) {
      sliderTimer = setTimeout(showJourneys, 240);
    }
  });
  byId("map-option").addEventListener("change", () => { activeMap = Number(byId("map-option").value); drawMap(); });
  new ResizeObserver(drawMap).observe(byId("journey-map"));
  byId("ask-form").addEventListener("submit", event => { event.preventDefault(); askQuestion(); });
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23"
  }).formatToParts().map((part) => [part.type, part.value]));
  byId("date").value = [parts.year, parts.month, parts.day].join("-");
  byId("time").value = [parts.hour, parts.minute].join(":");
  window.addEventListener("hashchange", setView);
  setView();
  try {
    const example = await api("/v1/example");
    if (formTouched) return;
    for (const field of fields) chooseStop(field, example[field]);
    byId("date").value = example.date;
    byId("time").value = example.time;
    await showJourneys();
  } catch {
    if (!formTouched) byId("result-context").textContent = t("Choose stops to compare journeys.","यात्राओं की तुलना के लिए स्टॉप चुनें।");
  }
}

initialize();
