-- Average daily mean temperature per city and season.
SELECT
    c.name                       AS city,
    d.season                     AS season,
    round(avg(w.temp_mean_c), 1) AS avg_temp_c
FROM fact_weather_daily AS w
JOIN dim_city AS c USING (city_id)
JOIN dim_date AS d USING (date)
GROUP BY c.name, d.season
ORDER BY c.name, d.season;
