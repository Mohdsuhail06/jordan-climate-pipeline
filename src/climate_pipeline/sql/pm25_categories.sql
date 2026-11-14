-- Number of days per city in each EPA PM2.5 category.
SELECT
    c.name           AS city,
    f.pm2_5_category AS category,
    count(*)         AS days
FROM fact_air_quality_daily AS f
JOIN dim_city AS c USING (city_id)
GROUP BY c.name, f.pm2_5_category
ORDER BY c.name, days DESC;
