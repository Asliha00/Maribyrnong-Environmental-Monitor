# Data Quality Report
_Generated 2026-10-27T04:09:32Z by data_pipeline/etl.py_

## Ingestion summary
| sensor_code   | sensor_name                      |   rows_read |   rows_inserted |   rows_duplicate |   values_rejected |   values_flagged |
|:--------------|:---------------------------------|------------:|----------------:|-----------------:|------------------:|-----------------:|
| FP-AMEN       | Footscray Park - Amenities Block |       22936 |           22936 |                0 |             22938 |            12645 |
| FP-LH         | Footscray Park - Leeds/Hopkins   |        8433 |            8433 |                0 |              8433 |             2767 |
| MCC-01        | MCC Air Quality Unit 1           |       50756 |           50756 |                0 |                 0 |               93 |
| MCC-02        | MCC Air Quality Unit 2           |       51100 |           51100 |                0 |                 6 |              168 |
| NM-CT         | Nicholson Mall Clock Tower       |       23867 |           23867 |                0 |                 4 |                0 |
| SALT-CC       | Saltwater Childcare Centre       |       35164 |           35164 |                0 |                 1 |            16932 |

## Coverage and metadata
| sensor_code   | first_reading_utc         | last_reading_utc          | land_use           | location_verified   |
|:--------------|:--------------------------|:--------------------------|:-------------------|:--------------------|
| FP-AMEN       | 2025-02-16 00:01:23+11:00 | 2026-02-16 23:58:54+11:00 | Parkland           | NO - confirm        |
| FP-LH         | 2025-02-16 10:12:30+11:00 | 2026-02-16 23:07:50+11:00 | Parkland           | NO - confirm        |
| MCC-01        | 2025-02-18 08:35:33+11:00 | 2026-02-16 23:42:46+11:00 | Transport corridor | NO - confirm        |
| MCC-02        | 2025-02-16 00:04:31+11:00 | 2026-02-16 23:46:25+11:00 | Industrial         | NO - confirm        |
| NM-CT         | 2025-02-16 00:14:20+11:00 | 2026-02-16 23:52:18+11:00 | Commercial         | NO - confirm        |
| SALT-CC       | 2025-02-16 00:09:33+11:00 | 2026-02-16 23:53:26+11:00 | Residential        | NO - confirm        |

## Daily completeness (temperature)
| sensor_code   |   avg_daily_completeness_pct |   valid_days |   days_with_data |
|:--------------|-----------------------------:|-------------:|-----------------:|
| FP-AMEN       |                         65.3 |          132 |              366 |
| FP-LH         |                         26.2 |           11 |              335 |
| MCC-01        |                         99.2 |          349 |              353 |
| MCC-02        |                         99.3 |          352 |              355 |
| NM-CT         |                         81.2 |          270 |              306 |
| SALT-CC       |                         98.9 |          365 |              366 |

## Rejected values (error_log)
| sensor_code   | error_type   | variable      |   n |
|:--------------|:-------------|:--------------|----:|
| FP-AMEN       | out_of_range | pm10          |   2 |
| FP-AMEN       | not_fitted   | co2_ppm       |   1 |
| FP-LH         | not_fitted   | co2_ppm       |   1 |
| MCC-02        | out_of_range | pm25          |   2 |
| MCC-02        | out_of_range | pm1           |   2 |
| MCC-02        | out_of_range | pm10          |   2 |
| NM-CT         | out_of_range | pressure_hpa  |   2 |
| NM-CT         | out_of_range | temperature_c |   2 |
| SALT-CC       | out_of_range | pm10          |   1 |

## Flagged values (kept, marked in qc_flags)
| sensor_code   | flag                 |     n |
|:--------------|:---------------------|------:|
| FP-AMEN       | humidity_saturated   | 12632 |
| FP-AMEN       | pm10_spike           |    10 |
| FP-AMEN       | pm25_spike           |     3 |
| FP-LH         | humidity_saturated   |  2752 |
| FP-LH         | pm10_spike           |    15 |
| MCC-01        | pm10_spike           |    19 |
| MCC-01        | pm1_spike            |    24 |
| MCC-01        | pm25_spike           |    26 |
| MCC-01        | temperature_flatline |    24 |
| MCC-02        | pm10_spike           |    31 |
| MCC-02        | pm1_spike            |    39 |
| MCC-02        | pm25_spike           |    41 |
| MCC-02        | temperature_flatline |    57 |
| SALT-CC       | humidity_saturated   | 16867 |
| SALT-CC       | pm10_spike           |    60 |
| SALT-CC       | pm1_spike            |     1 |
| SALT-CC       | pm25_spike           |     4 |

## Threshold exceedance days
| sensor_code   | label                          |   days |
|:--------------|:-------------------------------|-------:|
| FP-AMEN       | Extreme heat day (max >= 40°C) |      2 |
| FP-AMEN       | Hot day (max >= 35°C)          |     11 |
| FP-LH         | Hot day (max >= 35°C)          |      2 |
| MCC-01        | Extreme heat day (max >= 40°C) |      4 |
| MCC-01        | Hot day (max >= 35°C)          |     15 |
| MCC-01        | PM10 24-hour standard          |      1 |
| MCC-01        | PM2.5 24-hour standard         |      1 |
| MCC-02        | Extreme heat day (max >= 40°C) |      4 |
| MCC-02        | Hot day (max >= 35°C)          |     19 |
| MCC-02        | PM2.5 24-hour standard         |      1 |
| NM-CT         | Extreme heat day (max >= 40°C) |      4 |
| NM-CT         | Hot day (max >= 35°C)          |     11 |
| SALT-CC       | Extreme heat day (max >= 40°C) |      4 |
| SALT-CC       | Hot day (max >= 35°C)          |     20 |
