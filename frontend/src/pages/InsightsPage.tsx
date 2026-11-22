import { useQuery } from "@tanstack/react-query";
import { getSensors } from "../api/data";
import {
  getDisparities,
  getGreen,
  getPatterns,
  getRecommendations,
  getTrends,
  type Comparison,
  type Disparities,
  type GroupDifference,
  type Recommendation,
  type Recommendations,
} from "../api/insights";
import ChartFrame from "../components/ChartFrame";
import DifferencePlot, { describeDifference } from "../components/insights/DifferencePlot";
import DiurnalChart from "../components/insights/DiurnalChart";
import InfoTip, { GLOSSARY } from "../components/InfoTip";
import { ErrorMessage, Loading } from "../components/StatusMessage";
import { slotsByCode } from "../lib/palette";

const card = "rounded border border-slate-300 p-4 dark:border-slate-700";
const fmt = (v: number | null | undefined, digits = 2) =>
  v === null || v === undefined ? "–" : v.toFixed(digits);
const ci = (c: { low: number | null; high: number | null }, unit: string) =>
  c.low === null || c.high === null
    ? "interval not available"
    : `95% interval ${fmt(c.low)} to ${fmt(c.high)} ${unit}`;

function parkSentence(g: GroupDifference, when: string) {
  if (g.difference_c === null) return `No matched hours ${when}.`;
  const size = Math.abs(g.difference_c).toFixed(2);
  const verdict =
    g.direction === "falling"
      ? `parks were ${size} °C cooler than other sites`
      : g.direction === "rising"
        ? `parks were ${size} °C warmer than other sites`
        : `parks and other sites were not distinguishable (${g.difference_c >= 0 ? "+" : "−"}${size} °C)`;
  return `${when[0].toUpperCase()}${when.slice(1)}, ${verdict} (${ci({ low: g.low, high: g.high }, "°C")}; ${g.hours.toLocaleString("en-AU")} hours on ${g.days} days).`;
}

function RecommendationCard({ r }: { r: Recommendation }) {
  return (
    <li className={card}>
      <p className="text-xs font-semibold tracking-wide uppercase">
        <span
          className={
            r.priority === "high"
              ? "rounded bg-red-100 px-1.5 py-0.5 text-red-900 dark:bg-red-950 dark:text-red-100"
              : "rounded bg-slate-200 px-1.5 py-0.5 text-slate-800 dark:bg-slate-800 dark:text-slate-100"
          }
        >
          {r.priority === "high" ? "High priority" : "Medium priority"}
        </span>
      </p>
      <h3 className="mt-2 font-semibold">{r.title}</h3>
      <p className="mt-1 text-sm">{r.text}</p>
      <dl className="mt-2 space-y-1 text-sm">
        {r.evidence.map((e) => (
          <div key={e.label} className="flex flex-wrap gap-x-2">
            <dt className="text-slate-700 dark:text-slate-300">{e.label}:</dt>
            <dd>
              <span className="font-medium tabular-nums">
                {e.value === null ? "–" : `${e.value} ${e.unit}`}
              </span>{" "}
              <span className="text-slate-600 dark:text-slate-400">({e.detail})</span>
            </dd>
          </div>
        ))}
      </dl>
    </li>
  );
}

/** The limits of THIS data, built from the numbers (never a fixed sentence about the data). */
export function limitations(d: Disparities, r: Recommendations): string[] {
  const out = [`${d.months} month${d.months === 1 ? "" : "s"} of data (${d.start} to ${d.end})`];
  const single = r.network.single_sensor_land_uses.length;
  out.push(
    `${d.sites.length} sensor${d.sites.length === 1 ? "" : "s"}` +
      (single ? `, ${single} land use${single === 1 ? "" : "s"} with only one sensor` : ""),
  );
  const unverified = d.sites.filter((s) => !s.location_verified).length;
  if (unverified)
    out.push(`${unverified} sensor location${unverified === 1 ? "" : "s"} not yet verified`);
  if (r.network.low_completeness.length)
    out.push(
      `${r.network.low_completeness.map((x) => x.sensor_code).join(", ")} below 75% of expected readings`,
    );
  return out;
}

function trendWords(t: { slope_per_month: number; direction: string } | null, unit: string) {
  if (!t) return "not enough complete months";
  const change = `${t.slope_per_month >= 0 ? "+" : ""}${t.slope_per_month.toFixed(3)} ${unit}/month`;
  return t.direction === "no clear change"
    ? `${change} (no clear change)`
    : `${change} (${t.direction})`;
}

/** Insights (BUILD_PROMPT §4.3): the six project aims answered with computed numbers. */
export default function InsightsPage() {
  const disparities = useQuery({ queryKey: ["insights", "disparities"], queryFn: getDisparities });
  const green = useQuery({ queryKey: ["insights", "green"], queryFn: getGreen });
  const patterns = useQuery({ queryKey: ["insights", "patterns"], queryFn: getPatterns });
  const trends = useQuery({ queryKey: ["insights", "trends"], queryFn: getTrends });
  const recs = useQuery({ queryKey: ["insights", "recommendations"], queryFn: getRecommendations });
  const sensors = useQuery({ queryKey: ["sensors"], queryFn: getSensors, staleTime: 60_000 });
  const all = [disparities, green, patterns, trends, recs];
  const failed = all.find((q) => q.isError);
  if (failed)
    return <ErrorMessage error={failed.error} onRetry={() => all.forEach((q) => q.refetch())} />;
  if (all.some((q) => q.isPending))
    return <Loading label="Calculating insights from the sensor data…" />;
  const d = disparities.data!;
  const g = green.data!;
  const p = patterns.data!;
  const t = trends.data!;
  const r = recs.data!;
  const slots = slotsByCode((sensors.data?.sensors ?? []).map((s) => s.sensor_code));
  const rankOrder = (list: string[]) => (code: string) =>
    list.includes(code) ? list.indexOf(code) : list.length + 1;
  const byTemp = [...d.sites].sort(
    (a, b) =>
      rankOrder(d.rankings.temperature)(a.sensor_code) -
      rankOrder(d.rankings.temperature)(b.sensor_code),
  );
  const byPm = [...d.sites]
    .filter((s) => s.pm25_vs_others)
    .sort(
      (a, b) =>
        rankOrder(d.rankings.pm25)(a.sensor_code) - rankOrder(d.rankings.pm25)(b.sensor_code),
    );
  const diffRows = (key: "temperature_vs_others" | "pm25_vs_others", sites: typeof d.sites) =>
    sites.map((s) => ({
      label: s.sensor_code,
      badge: s.sensitive_receptor ? "sensitive site" : undefined,
      value: s[key] as Comparison | null,
    }));
  const diffTable = (
    key: "temperature_vs_others" | "pm25_vs_others",
    unit: string,
    sites: typeof d.sites,
  ) => (
    <table className="w-full text-left text-sm">
      <thead>
        <tr>
          <th scope="col">Site</th>
          <th scope="col">Land use</th>
          <th scope="col">Difference from the other sites ({unit})</th>
          <th scope="col">95% interval</th>
          <th scope="col">Matched days</th>
        </tr>
      </thead>
      <tbody>
        {sites.map((s) => {
          const c = s[key] as Comparison | null;
          return (
            <tr key={s.sensor_code}>
              <th scope="row" className="font-normal">
                {s.sensor_code} · {s.sensor_name}
                {s.sensitive_receptor && " (sensitive site)"}
              </th>
              <td>{s.land_use}</td>
              <td>{c ? describeDifference(c, unit) : "not enough data"}</td>
              <td>{c ? `${fmt(c.low)} to ${fmt(c.high)}` : "–"}</td>
              <td>{c?.days ?? 0}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-semibold">Insights</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-700 dark:text-slate-300">
          Calculated from the council's sensors for {d.start} to {d.end} ({d.days} days). Only
          periods with at least 75% of the expected readings are used, and flagged readings are left
          out. Sites are compared with each other <strong>on the same days</strong>, because some
          sensors have gaps in different seasons.
        </p>
      </header>

      <section aria-labelledby="recs-title" className="space-y-3">
        <h2 id="recs-title" className="text-xl font-semibold">
          Recommendations
        </h2>
        <ul className="grid gap-3 lg:grid-cols-2">
          {r.recommendations.map((rec) => (
            <RecommendationCard key={rec.id} r={rec} />
          ))}
        </ul>
      </section>

      <section aria-labelledby="where-title" className="space-y-3">
        <h2 id="where-title" className="text-xl font-semibold">
          Where is it hottest, and where is the air worst?
        </h2>
        <ChartFrame
          id="temp-diff"
          title="Temperature compared with the other sites, on the same days"
          subtitle="Dot: average daily difference; line: 95% interval. Red: warmer; blue: cooler; grey: not distinguishable from zero."
          chart={
            <DifferencePlot
              rows={diffRows("temperature_vs_others", byTemp)}
              unit="°C"
              words={["warmer", "cooler"]}
            />
          }
          table={diffTable("temperature_vs_others", "°C", byTemp)}
        />
        <ChartFrame
          id="pm-diff"
          title={
            <>
              PM2.5 compared with the other sites, on the same days
              <InfoTip label="PM2.5" text={GLOSSARY.pm25} />
            </>
          }
          subtitle="Red: more PM2.5 than the others; blue: less."
          chart={
            <DifferencePlot
              rows={diffRows("pm25_vs_others", byPm)}
              unit="µg/m³"
              words={["more", "less"]}
            />
          }
          table={diffTable("pm25_vs_others", "µg/m³", byPm)}
        />
        <div className={`${card} overflow-x-auto`}>
          <h3 className="font-semibold">Hot days and PM2.5 standard</h3>
          <table className="mt-2 w-full text-left text-sm">
            <caption className="sr-only">
              Hot days and days over the PM2.5 standard per site
            </caption>
            <thead>
              <tr>
                <th scope="col">Site</th>
                <th scope="col">Hot days reached ({g.hot_day_threshold_c} °C)</th>
                <th scope="col">Days over the PM2.5 24-hour standard</th>
              </tr>
            </thead>
            <tbody>
              {d.sites.map((s) => (
                <tr key={s.sensor_code}>
                  <th scope="row" className="font-normal">
                    {s.sensor_code} · {s.land_use}
                  </th>
                  <td>
                    {s.hot_day_share && s.hot_day_share.hot_days_reported
                      ? `${s.hot_day_share.hot_days_reached} of the ${s.hot_day_share.hot_days_reported} network hot days it reported (${fmt(s.hot_day_share.share_pct, 0)}%)`
                      : "–"}
                  </td>
                  <td>
                    {s.pm25_exceedance_days === null
                      ? "Not measured"
                      : `${s.pm25_exceedance_days} of ${s.pm25_days} valid days`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="equity-title" className="space-y-3">
        <h2 id="equity-title" className="text-xl font-semibold">
          Sensitive sites
        </h2>
        {d.equity.length === 0 ? (
          <p className="text-sm">
            No site is marked as a sensitive site (an administrator can mark one).
          </p>
        ) : (
          d.equity.map((e) => (
            <div key={e.sensor_code} className={card}>
              <h3 className="font-semibold">
                {e.sensor_name} ({e.land_use})
              </h3>
              <ul className="mt-1 list-disc pl-6 text-sm">
                {(["temperature", "pm25"] as const)
                  .filter((k) => e.comparison[k])
                  .map((k) => {
                    const c = e.comparison[k];
                    const unit = c.unit ?? "";
                    return (
                      <li key={k}>
                        {c.label}:{" "}
                        {describeDifference(
                          c,
                          unit,
                          k === "temperature" ? ["warmer", "cooler"] : ["more", "less"],
                        )}{" "}
                        than the other sites on the same days ({ci(c, unit)}; {c.days} days)
                        {c.direction === "rising" ? " — more exposed." : "."}
                      </li>
                    );
                  })}
              </ul>
            </div>
          ))
        )}
      </section>

      <section aria-labelledby="green-title" className={`${card} space-y-2`}>
        <h2 id="green-title" className="text-xl font-semibold">
          Do parks keep the area cooler?
        </h2>
        <p className="text-sm">
          Park sensors ({g.park_sensors.join(", ")}) compared with the other sites (
          {g.other_sensors.join(", ")}), only for hours when both groups had valid data.
        </p>
        <p>{parkSentence(g.all_hours, "over all matched hours")}</p>
        <p>
          {parkSentence(
            g.hot_afternoons,
            `on hot afternoons (12:00–18:00 on the ${g.hot_days} days when a site reached ${g.hot_day_threshold_c} °C)`,
          )}
        </p>
        <h3 className="pt-1 font-semibold">How far to trust this</h3>
        <ul className="list-disc pl-6 text-sm">
          {g.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="patterns-title" className="space-y-3">
        <h2 id="patterns-title" className="text-xl font-semibold">
          Daily and seasonal patterns
        </h2>
        {p.diurnal.temperature_c?.length > 0 && (
          <DiurnalChart
            id="diurnal-t"
            title="Temperature through an average day"
            unit="°C"
            series={p.diurnal.temperature_c}
            slots={slots}
          />
        )}
        {p.diurnal.pm25?.length > 0 && (
          <DiurnalChart
            id="diurnal-pm"
            title="PM2.5 through an average day"
            unit="µg/m³"
            series={p.diurnal.pm25}
            slots={slots}
          />
        )}
        <div className={`${card} overflow-x-auto`}>
          <h3 className="font-semibold">Seasonal average temperature (°C)</h3>
          <table className="mt-2 w-full text-left text-sm">
            <caption className="sr-only">Seasonal average temperature by site</caption>
            <thead>
              <tr>
                <th scope="col">Site</th>
                {(p.seasonal.temperature_c?.[0]?.seasons ?? []).map((s) => (
                  <th key={s.season} scope="col">
                    {s.season}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(p.seasonal.temperature_c ?? []).map((row) => (
                <tr key={row.sensor_code}>
                  <th scope="row" className="font-normal">
                    {row.sensor_code}
                  </th>
                  {row.seasons.map((s) => (
                    <td key={s.season}>
                      {s.mean === null
                        ? "No data"
                        : s.valid
                          ? fmt(s.mean, 1)
                          : `${fmt(s.mean, 1)} (incomplete)`}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="trends-title" className={`${card} space-y-2 overflow-x-auto`}>
        <h2 id="trends-title" className="text-xl font-semibold">
          Trends
        </h2>
        <p className="text-sm">
          The data cover {t.months} months. Over a single year the monthly averages mostly follow
          the seasons, so the change per month is shown two ways: on its own (mostly the season),
          and <strong>relative to the other sites</strong>, which removes the shared season and
          shows whether a site is drifting warmer or cooler than the rest.
        </p>
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Monthly temperature trend per site</caption>
          <thead>
            <tr>
              <th scope="col">Site</th>
              <th scope="col">Complete months</th>
              <th scope="col">Relative to the other sites</th>
              <th scope="col">On its own (mostly seasonal)</th>
            </tr>
          </thead>
          <tbody>
            {(t.trends.temperature_c ?? []).map((row) => (
              <tr key={row.sensor_code}>
                <th scope="row" className="font-normal">
                  {row.sensor_code} · {row.land_use}
                </th>
                <td>{row.months}</td>
                <td>{trendWords(row.relative, "°C")}</td>
                <td>{trendWords(row.absolute, "°C")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-labelledby="network-title" className={`${card} space-y-2`}>
        <h2 id="network-title" className="text-xl font-semibold">
          The sensor network
        </h2>
        <ul className="list-disc pl-6 text-sm">
          {r.network.low_completeness.map((x) => (
            <li key={x.sensor_code}>
              {x.sensor_code} sent {fmt(x.completeness_pct, 1)}% of its expected readings (below
              75%).
            </li>
          ))}
          {r.network.not_fitted.map((x) => (
            <li key={`${x.sensor_code}-${x.variable}`}>
              {x.sensor_code}: {x.label} always read zero, so it is treated as not fitted.
            </li>
          ))}
          {Object.entries(r.network.sensors_per_land_use).map(([lu, n]) => (
            <li key={lu}>
              {lu}: {n} active sensor{n === 1 ? "" : "s"}
              {n === 0
                ? " (not covered)"
                : n === 1
                  ? " (one sensor cannot separate the site from the land use)"
                  : ""}
            </li>
          ))}
        </ul>
      </section>

      <details className={card}>
        <summary className="cursor-pointer font-semibold">Methodology and limitations</summary>
        <div className="mt-2 space-y-2 text-sm">
          <p>
            <strong>Data.</strong> Hourly, daily and monthly averages from the council's sensors. A
            period counts only if it has at least 75% of the expected readings
            <InfoTip label="completeness" text={GLOSSARY.completeness} />. Flagged readings (spikes,
            frozen values, saturated humidity) are left out
            <InfoTip label="flagged readings" text={GLOSSARY.flagged} />.
          </p>
          <p>
            <strong>Comparing sites.</strong> For each site and day: the site's daily average minus
            the average of the other sites that day. The figure shown is the mean of those
            differences, with a 95% interval over days. Sites with fewer than 30 matched days are
            listed but not ranked.
          </p>
          <p>
            <strong>Hot days.</strong> Days on which the hottest site reached the council's
            &quot;hot day&quot; threshold ({g.hot_day_threshold_c} °C, editable by administrators).
            A site's hot-day figure counts only the hot days on which it reported.
          </p>
          <p>
            <strong>Parks.</strong> For each hour when at least one park sensor and one other sensor
            had valid data: average of the park sensors minus average of the others. One mean
            difference per day, then a 95% interval over days (hours within a day are not
            independent).
          </p>
          <p>
            <strong>Trends.</strong> Least-squares slope of valid monthly averages, with a 95%
            interval; &quot;rising&quot; or &quot;falling&quot; only when the whole interval is on
            one side of zero.
          </p>
          <p>
            <strong>Limitations.</strong> {limitations(d, r).join("; ")}. These results describe
            these sites, not the whole municipality, and differences can reflect how and where a
            sensor is mounted.
          </p>
        </div>
      </details>
    </div>
  );
}
