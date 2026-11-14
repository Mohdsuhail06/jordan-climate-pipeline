-- One row per city: climate and air-quality profile over the whole loaded period.
-- "Unhealthy" = daily PM2.5 above 35.4 µg/m³ (EPA: Unhealthy for Sensitive Groups or worse).
-- WHO 2021 guideline for daily PM2.5 is 15 µg/m³.
WITH weather AS (
    SELECT
        city_id,
        avg(temp_mean_c)                          AS avg_temp_c,
        max(temp_max_c)                           AS hottest_day_c,
        min(temp_min_c)                           AS coldest_night_c,
        sum(precipitation_mm) * 365.25 / count(*) AS rain_mm_per_year
    FROM fact_weather_daily
    GROUP BY city_id
),
air AS (
    SELECT
        city_id,
        count(*)                                                   AS air_days,
        avg(pm2_5_mean)                                            AS avg_pm25,
        100.0 * avg(CASE WHEN pm2_5_mean > 15 THEN 1 ELSE 0 END)   AS pct_days_above_who,
        100.0 * avg(CASE WHEN pm2_5_mean > 35.4 THEN 1 ELSE 0 END) AS pct_unhealthy_days
    FROM fact_air_quality_daily
    GROUP BY city_id
)
SELECT
    c.name                            AS city,
    round(w.avg_temp_c, 1)            AS avg_temp_c,
    round(w.hottest_day_c, 1)         AS hottest_day_c,
    round(w.coldest_night_c, 1)       AS coldest_night_c,
    round(w.rain_mm_per_year, 0)      AS rain_mm_per_year,
    round(a.avg_pm25, 1)              AS avg_pm25,
    round(a.pct_days_above_who, 1)    AS pct_days_above_who,
    round(a.pct_unhealthy_days, 1)    AS pct_unhealthy_days
FROM dim_city AS c
JOIN weather AS w USING (city_id)
JOIN air AS a USING (city_id)
ORDER BY pct_unhealthy_days DESC, avg_pm25 DESC;
