-- The 10 dustiest city-days by mean PM10 (coarse particles carried by dust storms).
SELECT
    c.name                    AS city,
    f.date                    AS date,
    round(f.pm10_mean, 1)     AS pm10_mean,
    round(f.pm2_5_mean, 1)    AS pm2_5_mean,
    f.pm2_5_category          AS category
FROM fact_air_quality_daily AS f
JOIN dim_city AS c USING (city_id)
ORDER BY f.pm10_mean DESC
LIMIT 10;
