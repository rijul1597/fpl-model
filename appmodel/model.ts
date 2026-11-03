/**
 * FPL Planner projected-points model. Everything lives here so it's easy to tune.
 *
 * xP per fixture =
 *   appearance pts × P(plays 60+) (+ sub-appearance pts × P(cameo))
 * + xG × goal pts(pos) + xA × assist pts        (xG/xA scaled by the opponent's defence and venue)
 * + P(clean sheet) × P(60+) × CS pts(pos)        (P(CS) = e^−(expected goals conceded in this fixture))
 * + bonus/90 × expMin/90
 * + defensive-contribution estimate (only when data + scoring exist)
 * + E[floor(saves / 3)] × saves points (goalkeepers; saves scaled by the opponent's attack)
 * − E[floor(Poisson(goals conceded) / 2)] × GC penalty(pos) × P(60+)
 *
 * Team ratings come from this season's data, because FPL's strength_* fields are zero in the live API:
 *   attack  = club xG per match ÷ league average
 *   defence = club xG conceded per match ÷ league average (above 1 = leakier than average)
 * Both are shrunk toward 1 by TEAM_PRIOR_MATCHES. Actual goals stand in for a club with no xG data.
 */

// ===================== Tunable constants =====================
export const MODEL = {
  HORIZON_MAX: 8, // gameweeks projected
  BASE_GOALS: 1.4, // league-average goals per team per match
  HOME_ADVANTAGE: 1.1, // home attacks ×1.1, away attacks ÷1.1
  TEAM_PRIOR_MATCHES: 5, // team ratings start from this many league-average matches
  CS_MIN: 0.05,
  CS_MAX: 0.6,
  FULL_MINUTES: 86, // expected minutes when a player plays 60+
  SUB_MINUTES: 22, // expected minutes on a cameo
  START_WEIGHT: 0.6, // weight of start-rate vs minutes-share in P(60+)
  EARLY_SEASON_P60: 0.6, // used before any gameweek has finished
  RATE_SHRINK_MINUTES: 270, // prior weight for position-average per-90 rates
  POSITION_PRIOR_MINUTES: 450,
  SAVES_PER_POINT: 3, // the saves score is awarded per this many saves
  DC_THRESHOLD: { GKP: Infinity, DEF: 10, MID: 12, FWD: 12 } as Record<string, number>,
  DC_MAX_P: 0.85,
  // Fallbacks used ONLY if bootstrap-static game_config.scoring is missing a key.
  FALLBACK_SCORING: {
    long_play: 2,
    short_play: 1,
    goals_scored: { GKP: 10, DEF: 6, MID: 5, FWD: 4 },
    assists: 3,
    clean_sheets: { GKP: 4, DEF: 4, MID: 1, FWD: 0 },
    goals_conceded: { GKP: -1, DEF: -1, MID: 0, FWD: 0 },
    saves: 1,
  } as Record<string, number | Record<string, number>>,
};

// ===================== Types =====================
export type Element = {
  id: number;
  web_name: string;
  first_name: string;
  second_name: string;
  team: number;
  element_type: number;
  now_cost: number;
  minutes: number;
  starts?: number;
  saves?: number;
  saves_per_90?: number | string;
  bonus: number;
  form: string;
  status: string;
  news: string;
  total_points: number;
  chance_of_playing_next_round: number | null;
  expected_goals?: number | string;
  expected_goals_conceded?: number | string;
  expected_goals_per_90?: number | string;
  expected_assists_per_90?: number | string;
  defensive_contribution_per_90?: number | string | null;
};
export type Team = {
  id: number;
  name: string;
  short_name: string;
  strength_attack_home: number;
  strength_attack_away: number;
  strength_defence_home: number;
  strength_defence_away: number;
};
export type ElementType = { id: number; singular_name_short: string; plural_name: string };
export type GwEvent = { id: number; name: string; is_current: boolean; is_next: boolean; finished: boolean; deadline_time: string };
export type Chip = { id: number; name: string; number?: number; start_event: number; stop_event: number; chip_type?: string };
export type Bootstrap = {
  elements: Element[];
  teams: Team[];
  element_types: ElementType[];
  events: GwEvent[];
  chips: Chip[];
  game_config?: { scoring?: Record<string, number | Record<string, number>> };
};
export type Fixture = {
  id: number;
  event: number | null;
  team_h: number;
  team_a: number;
  team_h_difficulty: number;
  team_a_difficulty: number;
  finished: boolean;
  kickoff_time: string | null;
  team_h_score?: number | null;
  team_a_score?: number | null;
};

export type Parts = {
  appearance: number;
  goals: number;
  assists: number;
  cleanSheet: number;
  bonus: number;
  defcon: number;
  saves: number;
  conceded: number;
};
export type FixtureXp = {
  gw: number;
  opp: number;
  home: boolean;
  fdr: number;
  parts: Parts;
  total: number;
  xg: number;
  xa: number;
  pCS: number;
  /** Multiplier on the player's xG/xA for this opponent and venue (1 = average fixture). */
  matchup: number;
  /** Goals his club is expected to concede in this fixture. */
  expConceded: number;
};
export type GwXp = { gw: number; total: number; fixtures: FixtureXp[]; p60: number; expMin: number };
export type PlayerXp = { p60: number; expMin: number; byGw: Map<number, GwXp> };
export type TeamFixture = { gw: number; opp: number; home: boolean; fdr: number };
export type TeamRating = { attack: number; defence: number; played: number };

// ===================== Helpers =====================
const num = (v: unknown) => {
  const n = typeof v === "string" ? parseFloat(v) : typeof v === "number" ? v : 0;
  return Number.isFinite(n) ? n : 0;
};
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const sum = (p: Parts) => p.appearance + p.goals + p.assists + p.cleanSheet + p.bonus + p.defcon + p.saves + p.conceded;
const OUT_INDEFINITELY = /unknown return date/i;

// Equivalent to sum(k >= 1, P(N >= 2k)), using floor(N/2) = (N - 1{N odd})/2.
export const expectedConcededPairs = (lambda: number) => lambda / 2 + Math.expm1(-2 * lambda) / 4;

/** E[floor(N / d)] for N ~ Poisson(lambda), i.e. the sum over k >= 1 of P(N >= k·d). */
export function expectedFloorDiv(lambda: number, d: number) {
  if (!(lambda > 0) || !(d >= 1)) return 0;
  const maxN = Math.ceil(lambda + 12 * Math.sqrt(lambda) + 20);
  let probability = Math.exp(-lambda);
  let total = 0;
  for (let n = 1; n <= maxN; n++) {
    probability *= lambda / n;
    total += Math.floor(n / d) * probability;
  }
  return total;
}

export function newsReturnDate(news: string, nextDeadline: string): number | null {
  const match = /(?:expected\s+back|suspended\s+until)\s+(\d{1,2})\s+([a-z]{3,9})(?:\s+(\d{4}))?/i.exec(news);
  if (!match) return null;
  const months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
  const month = months.indexOf((match[2] ?? "").slice(0, 3).toLowerCase());
  const day = Number(match[1]);
  const reference = new Date(nextDeadline);
  if (month < 0 || !Number.isFinite(reference.getTime())) return null;
  let year = match[3] ? Number(match[3]) : reference.getUTCFullYear();
  // A December deadline and January return refer to the following calendar year.
  if (!match[3] && month < reference.getUTCMonth() - 6) year += 1;
  const date = Date.UTC(year, month, day);
  return new Date(date).getUTCDate() === day ? date : null;
}

/** Season attack and defence ratings per club, 1 = league average (see the header comment). */
export function teamRatings(b: Bootstrap, fixtures: Fixture[]): Map<number, TeamRating> {
  const stats = new Map(b.teams.map((t) => [t.id, { played: 0, xgFor: 0, xgAgainst: 0, goalsFor: 0, goalsAgainst: 0 }]));
  for (const f of fixtures) {
    if (!f.finished) continue;
    const home = stats.get(f.team_h);
    const away = stats.get(f.team_a);
    if (!home || !away) continue;
    const homeGoals = f.team_h_score ?? 0;
    const awayGoals = f.team_a_score ?? 0;
    home.played += 1;
    home.goalsFor += homeGoals;
    home.goalsAgainst += awayGoals;
    away.played += 1;
    away.goalsFor += awayGoals;
    away.goalsAgainst += homeGoals;
  }
  const keeper = b.element_types.find((t) => t.singular_name_short === "GKP")?.id ?? 1;
  for (const e of b.elements) {
    const s = stats.get(e.team);
    if (!s) continue;
    s.xgFor += num(e.expected_goals);
    // Exactly one goalkeeper is on the pitch, so a club's keepers together cover its xG conceded.
    if (e.element_type === keeper) s.xgAgainst += num(e.expected_goals_conceded);
  }
  const rows = [...stats.entries()].map(([id, s]) => ({
    id,
    played: s.played,
    scored: s.xgFor > 0 ? s.xgFor : s.goalsFor,
    conceded: s.xgAgainst > 0 ? s.xgAgainst : s.goalsAgainst,
  }));
  const matches = rows.reduce((a, r) => a + r.played, 0);
  const leagueScored = matches > 0 ? rows.reduce((a, r) => a + r.scored, 0) / matches : 0;
  const leagueConceded = matches > 0 ? rows.reduce((a, r) => a + r.conceded, 0) / matches : 0;
  const k = MODEL.TEAM_PRIOR_MATCHES;
  // (played × own ratio + k × 1) / (played + k), where own ratio = per-match rate ÷ league rate.
  const rate = (total: number, played: number, league: number) => (league > 0 && played > 0 ? (total / league + k) / (played + k) : 1);
  return new Map(
    rows.map((r) => [
      r.id,
      { attack: rate(r.scored, r.played, leagueScored), defence: rate(r.conceded, r.played, leagueConceded), played: r.played },
    ]),
  );
}

export type Model = ReturnType<typeof buildModel>;

export function buildModel(b: Bootstrap, fixtures: Fixture[]) {
  const teams = new Map(b.teams.map((t) => [t.id, t]));
  const elements = new Map(b.elements.map((e) => [e.id, e]));
  const posName = new Map(b.element_types.map((t) => [t.id, t.singular_name_short]));
  const scoring = b.game_config?.scoring ?? {};

  const score = (key: string, pos: string): number => {
    const v = key in scoring ? scoring[key] : MODEL.FALLBACK_SCORING[key];
    if (v == null) return 0;
    if (typeof v === "number") return v;
    return num(v[pos]);
  };
  const hasDcScoring = "defensive_contribution" in scoring;
  const positionMeans = new Map<number, { xg: number; xa: number; bonus: number }>();
  for (const position of b.element_types) {
    const regulars = b.elements.filter((e) => e.element_type === position.id && e.minutes >= MODEL.POSITION_PRIOR_MINUTES);
    const n = regulars.length || 1;
    positionMeans.set(position.id, {
      xg: regulars.reduce((a, e) => a + num(e.expected_goals_per_90), 0) / n,
      xa: regulars.reduce((a, e) => a + num(e.expected_assists_per_90), 0) / n,
      bonus: regulars.reduce((a, e) => a + e.bonus * 90 / e.minutes, 0) / n,
    });
  }

  const ratings = teamRatings(b, fixtures);
  const neutral: TeamRating = { attack: 1, defence: 1, played: 0 };
  const rating = (team: number) => ratings.get(team) ?? neutral;

  const current = b.events.find((e) => e.is_current);
  const nextEv = b.events.find((e) => e.is_next);
  const lastGw = Math.max(...b.events.map((e) => e.id));
  const nextGw = nextEv?.id ?? Math.min(lastGw, (current?.id ?? 0) + 1);
  const finishedCount = b.events.filter((e) => e.finished).length;
  const horizonGws = (h: number) => {
    const out: number[] = [];
    for (let g = nextGw; g < nextGw + h && g <= lastGw; g++) out.push(g);
    return out;
  };

  // team -> gw -> fixtures
  const teamFx = new Map<number, Map<number, TeamFixture[]>>();
  for (const f of fixtures) {
    if (f.event == null || f.event < nextGw) continue;
    const add = (team: number, tf: TeamFixture) => {
      const m = teamFx.get(team) ?? new Map<number, TeamFixture[]>();
      const list = m.get(tf.gw) ?? [];
      list.push(tf);
      m.set(tf.gw, list);
      teamFx.set(team, m);
    };
    add(f.team_h, { gw: f.event, opp: f.team_a, home: true, fdr: f.team_h_difficulty });
    add(f.team_a, { gw: f.event, opp: f.team_h, home: false, fdr: f.team_a_difficulty });
  }
  const teamFixtures = (team: number, gw: number) => teamFx.get(team)?.get(gw) ?? [];

  const cache = new Map<number, PlayerXp>();

  function availability(el: Element, gw: number) {
    let base: number;
    if (finishedCount === 0) base = MODEL.EARLY_SEASON_P60;
    else {
      const share = clamp(el.minutes / (finishedCount * 90), 0, 1);
      const startRate = clamp(num(el.starts ?? el.minutes / 90) / finishedCount, 0, 1);
      base = MODEL.START_WEIGHT * startRate + (1 - MODEL.START_WEIGHT) * share;
    }
    let cf = 1;
    if (gw === nextGw) cf = el.chance_of_playing_next_round != null ? clamp(el.chance_of_playing_next_round / 100, 0, 1) : 1;
    else {
      const nextDeadline = b.events.find((e) => e.id === nextGw)?.deadline_time ?? "";
      const returnDate = newsReturnDate(el.news, nextDeadline);
      const deadline = b.events.find((e) => e.id === gw)?.deadline_time;
      if (returnDate != null && deadline && Date.parse(deadline) < returnDate) cf = 0;
    }
    // Gone from the club, or injured with no return date: plan without him for the whole horizon.
    if (el.status === "u" || (el.chance_of_playing_next_round === 0 && OUT_INDEFINITELY.test(el.news))) cf = 0;
    const p60 = clamp(base, 0, 1) * cf;
    const pSub = Math.max(0, clamp(base + 0.2, 0, 1) * cf - p60);
    const expMin = p60 * MODEL.FULL_MINUTES + pSub * MODEL.SUB_MINUTES;
    return { p60, pSub, expMin };
  }

  function project(id: number): PlayerXp {
    const hit = cache.get(id);
    if (hit) return hit;
    const el = elements.get(id);
    if (!el) return { p60: 0, expMin: 0, byGw: new Map() };
    const pos = posName.get(el.element_type) ?? "MID";
    if (!teams.has(el.team)) return { p60: 0, expMin: 0, byGw: new Map() };
    const own = rating(el.team);
    const nextAvailability = availability(el, nextGw);
    const shrink = el.minutes / (el.minutes + MODEL.RATE_SHRINK_MINUTES);
    const prior = positionMeans.get(el.element_type) ?? { xg: 0, xa: 0, bonus: 0 };
    const xg90 = num(el.expected_goals_per_90) * shrink + prior.xg * (1 - shrink);
    const xa90 = num(el.expected_assists_per_90) * shrink + prior.xa * (1 - shrink);
    const bonus90 = (el.minutes > 0 ? el.bonus * 90 / el.minutes : 0) * shrink + prior.bonus * (1 - shrink);
    const saves90 = el.saves_per_90 != null ? num(el.saves_per_90) : el.minutes > 0 ? num(el.saves) * 90 / el.minutes : 0;
    const dc90 = el.defensive_contribution_per_90 != null ? num(el.defensive_contribution_per_90) : null;
    const dcPts = hasDcScoring ? score("defensive_contribution", pos) : 0;

    const byGw = new Map<number, GwXp>();
    for (const gw of horizonGws(MODEL.HORIZON_MAX)) {
      const { p60, pSub, expMin } = availability(el, gw);
      const fxs: FixtureXp[] = teamFixtures(el.team, gw).flatMap((tf) => {
        if (!teams.has(tf.opp)) return [];
        const opp = rating(tf.opp);
        const venue = tf.home ? MODEL.HOME_ADVANTAGE : 1 / MODEL.HOME_ADVANTAGE;
        const matchup = opp.defence * venue; // how much easier than average it is to create chances here
        const oppAttack = opp.attack / venue; // the opponent's attack, adjusted for their venue
        const teamGC = MODEL.BASE_GOALS * oppAttack * own.defence;
        const pCS = clamp(Math.exp(-teamGC), MODEL.CS_MIN, MODEL.CS_MAX);
        const xg = (xg90 * expMin) / 90 * matchup;
        const xa = (xa90 * expMin) / 90 * matchup;
        let defcon = 0;
        if (dc90 != null && dcPts > 0) {
          const thr = MODEL.DC_THRESHOLD[pos] ?? Infinity;
          defcon = clamp((dc90 / thr - 0.6) / 0.8, 0, MODEL.DC_MAX_P) * p60 * dcPts;
        }
        const expSaves = (saves90 * MODEL.FULL_MINUTES) / 90 * oppAttack;
        const parts: Parts = {
          appearance: p60 * score("long_play", pos) + pSub * score("short_play", pos),
          goals: xg * score("goals_scored", pos),
          assists: xa * score("assists", pos),
          cleanSheet: pCS * p60 * score("clean_sheets", pos),
          bonus: (bonus90 * expMin) / 90,
          defcon,
          saves: pos === "GKP" ? p60 * expectedFloorDiv(expSaves, MODEL.SAVES_PER_POINT) * score("saves", pos) : 0,
          conceded: expectedConcededPairs(teamGC) * p60 * score("goals_conceded", pos),
        };
        return [{ gw, opp: tf.opp, home: tf.home, fdr: tf.fdr, parts, total: sum(parts), xg, xa, pCS, matchup, expConceded: teamGC }];
      });
      byGw.set(gw, { gw, total: fxs.reduce((a, f) => a + f.total, 0), fixtures: fxs, p60, expMin });
    }
    const res = { p60: nextAvailability.p60, expMin: nextAvailability.expMin, byGw };
    cache.set(id, res);
    return res;
  }

  const xpGw = (id: number, gw: number) => project(id).byGw.get(gw)?.total ?? 0;
  const xpHorizon = (id: number, h: number) => horizonGws(h).reduce((a, g) => a + xpGw(id, g), 0);

  return { b, teams, elements, posName, nextGw, lastGw, horizonGws, teamFixtures, project, xpGw, xpHorizon, score, ratings, rating };
}
