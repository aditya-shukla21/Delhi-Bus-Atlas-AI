/* Local bilingual intent classification. All travel facts come from planner results. */
(() => {
  "use strict";
  const examples = {
    compare: ["Compare the bus options", "What do I give up for a quieter trip", "Is the quieter bus worth the extra time", "How many extra minutes for less crowding", "Compare fastest and most comfortable", "कम भीड़ के लिए कितनी देर लगेगी", "सबसे तेज़ और आरामदायक बस की तुलना करें", "इन विकल्पों में क्या अंतर है", "kam bheed ke liye kitna extra time"],
    fast: ["Which is the fastest bus", "Which one arrives earliest", "I am in a hurry", "I need the quickest route", "What time do I arrive on the fastest journey", "सबसे जल्दी कौन सी बस पहुंचेगी", "सबसे तेज रास्ता", "जल्दी पहुँचना है", "jaldi pahunchna hai"],
    quiet: ["Which bus is least crowded", "Find the quietest journey", "I prefer a less busy bus", "Which has the lowest crowd level", "सबसे कम भीड़ किस बस में है", "कम भीड़ वाली बस बताओ", "भीड़ से बचना है", "kam bheed wali bus"],
    later: ["Would leaving later help", "Should I wait twenty minutes before departing", "Is there a quieter bus if I leave later", "What if I leave 20 minutes later", "थोड़ी देर बाद निकलूं तो भीड़ कम होगी", "बाद में निकलने से कितना फायदा होगा", "अगर मैं 20 मिनट बाद निकलूँ", "baad mein niklu toh"],
    changes: ["Do I have to change buses", "Which routes are direct", "How many transfers on each option", "Where do I change buses", "Where is my transfer stop", "Which route needs a transfer", "How many changes are there", "I don't want to switch buses", "क्या बस बदलनी होगी", "कहाँ बस बदलूँ", "सीधी बस कौन सी है", "kitni bus badalni hai"],
    evidence: ["How reliable is this estimate", "How much of the route has evidence", "How confident are you", "Is there missing data", "What does unknown mean", "अनुमान कितना भरोसेमंद है", "कितने रास्ते का डेटा है", "अज्ञात का मतलब क्या है", "bharosa kitna hai"],
    seat: ["Will I get a seat", "Can you guarantee a seat", "Are there seats available", "Will I have to stand", "क्या सीट मिलेगी", "क्या मुझे खड़े होकर जाना होगा", "बैठने की जगह मिलेगी", "seat milegi kya"],
    stretch: ["Where is the busiest stretch", "Which part of my ride is most crowded", "Between which stops is crowding highest", "सबसे ज्यादा भीड़ कहाँ है", "किस हिस्से में भीड़ सबसे अधिक है", "किन स्टॉप के बीच सबसे अधिक भीड़ है"],
    help: ["How much is a ticket", "What is the fare", "Where can I buy tickets", "What is the weather", "Is the bus running late right now", "Track the live bus location", "Is the bus wheelchair accessible", "What is the metro schedule", "किराया कितना है", "टिकट कैसे खरीदें", "आज मौसम कैसा है", "बस अभी कहाँ है", "मेट्रो कितने बजे है"]
  };
  const docs = Object.entries(examples).flatMap(([intent, phrases]) => phrases.map(text => ({intent, text})));
  function features(text) {
    const words = text.normalize("NFKC").toLowerCase().match(/[\p{L}\p{N}\p{M}]+/gu) || [];
    const counts = new Map();
    for (const word of words) {
      counts.set("w:" + word, (counts.get("w:" + word) || 0) + 2);
      const padded = "^" + word + "$";
      for (let i = 0; i + 2 < padded.length; i++) {
        const gram = padded.slice(i, i + 3);
        counts.set(gram, (counts.get(gram) || 0) + 1);
      }
    }
    return counts;
  }
  const df = new Map();
  for (const doc of docs) {
    doc.terms = features(doc.text);
    for (const term of doc.terms.keys()) df.set(term, (df.get(term) || 0) + 1);
  }
  function vector(terms) {
    const values = new Map();
    for (const [term, count] of terms) {
      values.set(term, (1 + Math.log(count)) * (1 + Math.log((docs.length + 1) / (1 + (df.get(term) || 0)))));
    }
    const norm = Math.hypot(...values.values()) || 1;
    for (const [key, val] of values) values.set(key, val / norm);
    return values;
  }
  for (const doc of docs) doc.vector = vector(doc.terms);
  function classify(text) {
    const query = vector(features(String(text).slice(0, 500)));
    const scores = docs.map(doc => {
      let score = 0;
      for (const [term, val] of query) score += val * (doc.vector.get(term) || 0);
      return {intent: doc.intent, score};
    }).sort((a, b) => b.score - a.score);
    const best = scores[0];
    const other = scores.find(item => item.intent !== best.intent);
    return best.score >= 0.26 && best.score - other.score >= 0.025 ? best.intent : "help";
  }
  const hindi = {Low:"कम",Medium:"मध्यम",High:"अधिक","Very High":"बहुत अधिक",Unknown:"अज्ञात"};
  const routes = option => option.legs.map(leg => leg.route).join(" → ");
  async function answer(params, api) {
    const hi = params.lang === "hi";
    const say = (en, hiText) => hi ? hiText : en;
    const band = value => hi ? (hindi[value] || hindi.Unknown) : value;
    const reply = text => ({answer: text, engine: "local-intent"});
    const intent = classify(params.q);
    if (intent === "help") return reply(say("I can compare the displayed buses, explain transfers or crowd evidence, or check a later departure. Try “Which bus arrives earliest?”", "मैं दिख रही बसों, बस बदलने की जगह, भीड़ के अनुमान या बाद में निकलने के बारे में बता सकता हूँ। पूछें “सबसे जल्दी कौन सी बस पहुँचेगी?”"));
    if (intent === "seat") return reply(say("The October tickets measure relative passenger load. They contain no seat inventory or vehicle capacity, so even a Low estimate cannot guarantee a seat.", "अक्टूबर के टिकटों से यात्रियों की सापेक्ष संख्या का अनुमान मिलता है। खाली सीटों और बस की क्षमता का डेटा उपलब्ध नहीं है। कम भीड़ में भी सीट की गारंटी नहीं है।"));
    const request = {from: params.from, to: params.to, time: params.time, date: params.date, preference: params.preference ?? 0};
    if (intent === "later") {
      const data = await api("/v1/advice", request);
      if (!data.baseline) return reply(say("There is no scheduled journey to use for this comparison.", "तुलना के लिए चुने हुए समय पर कोई निर्धारित यात्रा नहीं मिली।"));
      const numeric = String(params.q).toLowerCase().replace(/[०-९]/g, x => String(x.charCodeAt(0)-0x966));
      const rawDelay = numeric.match(/(\d{1,3})\s*(?:min|मिनट)/);
      const phrases = [[10, /\bten\b|दस मिनट/], [20, /\btwenty\b|बीस मिनट/], [30, /\bthirty\b|तीस मिनट/]];
      const delay = rawDelay ? Number(rawDelay[1]) : phrases.find(([,re])=>re.test(numeric))?.[0];
      if (delay !== undefined && ![10,20,30].includes(delay)) return reply(say("The advisor can check 10, 20 or 30 minutes later. Change the departure field for a different interval.", "सलाहकार 10, 20 या 30 मिनट बाद की जाँच करता है। दूसरे अंतराल के लिए प्रस्थान समय बदलें।"));
      const w = delay === undefined ? data.recommendation : data.windows.find(win=>win.offset_min===delay);
      if (w && !w.qualifies) return reply(say(`For the window starting at ${w.time} (+${w.offset_min} min), I found no quieter departure that met the evidence and arrival-time limits.`, `${w.time} बजे से शुरू होने वाले समय खंड में (${w.offset_min} मिनट बाद) पर्याप्त प्रमाण और आगमन समय की सीमा के भीतर कम भीड़ वाला विकल्प नहीं मिला।`));
      if (!w) return reply(say("The 10-, 20- and 30-minute checks found no later option meeting the evidence and arrival-time limits.", "10, 20 और 30 मिनट बाद की जाँच में पर्याप्त प्रमाण और आगमन समय की सीमा के भीतर कम भीड़ वाला विकल्प नहीं मिला।"));
      const alt = w.alternative;
      return reply(say(`Try leaving at ${w.time} (+${w.offset_min} min). Take ${alt.routes.join(" → ")} at ${alt.departure}, arriving at ${alt.arrival}. Estimated crowding changes from ${band(data.baseline.level)} to ${band(alt.level)}.`, `${w.time} बजे निकलें (${w.offset_min} मिनट बाद)। ${alt.departure} पर ${alt.routes.join(" → ")} लें। आगमन ${alt.arrival} बजे है। अनुमानित भीड़ ${band(data.baseline.level)} से ${band(alt.level)} हो जाती है।`));
    }
    const {options} = await api("/v1/plan", request);
    if (!options.length) return reply(say("There are no scheduled options for this search. Try another stop or time.", "इस खोज के लिए कोई निर्धारित यात्रा नहीं मिली। दूसरा स्टॉप या समय चुनें।"));
    const fastest = options.reduce((a,b) => a.time_rank <= b.time_rank ? a : b);
    const quiet = options.reduce((a,b) => a.comfort_rank <= b.comfort_rank ? a : b);
    const first = options[0];
    const desc = o => say(`${routes(o)} departs at ${o.departure}, arrives at ${o.arrival} and takes ${o.duration_min} min including waits. Estimated crowding: ${band(o.level)}.`, `${routes(o)} का प्रस्थान ${o.departure} बजे और आगमन ${o.arrival} बजे है। प्रतीक्षा सहित ${o.duration_min} मिनट लगते हैं। अनुमानित भीड़: ${band(o.level)}।`);
    if (intent === "fast") return reply(desc(fastest));
    if (intent === "quiet" || intent === "compare") {
      if (quiet.level === "Unknown") return reply(say("There is too little evidence to identify a quieter journey. " + desc(fastest), "कम भीड़ वाली यात्रा चुनने के लिए पर्याप्त प्रमाण नहीं है। " + desc(fastest)));
      if (intent === "quiet") return reply(desc(quiet));
      if (quiet === fastest) return reply(say("The same option leads both rankings. ", "दोनों क्रमों में यही विकल्प पहले आता है। ") + desc(fastest));
      const diff = quiet.duration_min - fastest.duration_min;
      return reply(say(`The fastest is ${routes(fastest)} (${fastest.duration_min} min, ${band(fastest.level)}). The comfort choice is ${routes(quiet)} (${quiet.duration_min} min, ${band(quiet.level)}), adding ${diff} min. Times include waits.`, `सबसे तेज़ ${routes(fastest)} है (${fastest.duration_min} मिनट, भीड़ ${band(fastest.level)})। आराम के लिए ${routes(quiet)} है (${quiet.duration_min} मिनट, भीड़ ${band(quiet.level)})। प्रतीक्षा सहित ${diff} मिनट अतिरिक्त लगते हैं।`));
    }
    if (intent === "changes") return reply(options.map(o => {
      const changes = o.legs.slice(0,-1).map(l=>l.destination).join(", ");
      return routes(o) + " — " + (o.transfers ? say(`change at ${changes}.`, `${changes} पर बस बदलें।`) : say("direct.", "सीधी बस।"));
    }).join(" "));
    if (intent === "evidence") {
      const covered = Math.round(first.coverage * 100);
      return reply(say(`For ${routes(first)}, supported estimates cover ${covered}% of scheduled riding time. Each published stretch needs at least 10 supporting ticket crossings across 3 distinct dates. Coverage measures availability of evidence, not accuracy.`, `${routes(first)} में निर्धारित सवारी समय के ${covered}% के लिए अनुमान उपलब्ध है। हर प्रकाशित खंड में कम से कम 3 अलग तारीखों पर 10 सहायक टिकट हैं। यह प्रतिशत डेटा की उपलब्धता बताता है।`));
    }
    const segments = first.legs.flatMap(leg=>leg.segments).filter(s=>Number.isFinite(s.load)).sort((a,b)=>b.load-a.load);
    if (!segments.length) return reply(say("There is insufficient evidence to identify a busy stretch on the first option.", "पहले विकल्प के सबसे भीड़ वाले खंड के लिए पर्याप्त प्रमाण नहीं है।"));
    const s = segments[0];
    return reply(say(`Among measured stretches on the first option, ${s.from_name} → ${s.to_name} has the highest estimated ticketed load (${band(s.level)}; ${s.tickets} ticket crossings across ${s.days} dates).`, `पहले विकल्प के मापे गए खंडों में ${s.from_name} → ${s.to_name} पर अनुमानित भीड़ सबसे अधिक है (${band(s.level)}; ${s.days} तारीखों के ${s.tickets} टिकट)।`));
  }
  globalThis.JourneyAI = {answer, classify};
})();
