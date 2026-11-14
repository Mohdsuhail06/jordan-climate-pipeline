-- Does rain clean the air? Compare particle levels on rainy and dry days.
SELECT
    CASE WHEN w.precipitation_mm >= 1 THEN 'Rainy (>= 1 mm)' ELSE 'Dry' END AS day_type,
    count(*)                    AS days,
    round(avg(a.pm2_5_mean), 1) AS avg_pm25,
    round(avg(a.pm10_mean), 1)  AS avg_pm10
FROM fact_weather_daily AS w
JOIN fact_air_quality_daily AS a USING (city_id, date)
GROUP BY day_type
ORDER BY day_type;
