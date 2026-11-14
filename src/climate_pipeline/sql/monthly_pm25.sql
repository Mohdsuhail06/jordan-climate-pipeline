-- Average PM2.5 per city and calendar month: shows the seasonal pattern (spring dust storms).
SELECT
    c.name                  AS city,
    d.month                 AS month,
    round(avg(f.pm2_5_mean), 1) AS avg_pm25
FROM fact_air_quality_daily AS f
JOIN dim_city AS c USING (city_id)
JOIN dim_date AS d USING (date)
GROUP BY c.name, d.month
ORDER BY c.name, d.month;
