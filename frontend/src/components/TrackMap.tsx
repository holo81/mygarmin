import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import type { Sample } from "../api/types";

/**
 * Renders a GPS track using MapLibre GL with the free OSM raster tiles (no API
 * key, no third-party analytics). Only rendered when GPS samples exist.
 */
export function TrackMap({ samples }: { samples: Sample[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const coords = samples
      .filter((s) => s.latitude != null && s.longitude != null)
      .map((s) => [s.longitude as number, s.latitude as number] as [number, number]);
    if (coords.length < 2) return;

    const map = new maplibregl.Map({
      container: ref.current,
      style: {
        version: 8,
        sources: {
          osm: {
            type: "raster",
            tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
            tileSize: 256,
            attribution: "© OpenStreetMap contributors",
          },
        },
        layers: [{ id: "osm", type: "raster", source: "osm" }],
      },
      attributionControl: {},
    });

    map.on("load", () => {
      map.addSource("track", {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: { type: "LineString", coordinates: coords },
        },
      });
      map.addLayer({
        id: "track-line",
        type: "line",
        source: "track",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": getComputedStyle(document.documentElement)
            .getPropertyValue("--accent")
            .trim() || "#3fb6b2",
          "line-width": 4,
        },
      });

      // Start / end markers.
      new maplibregl.Marker({ color: "#3fb950" }).setLngLat(coords[0]).addTo(map);
      new maplibregl.Marker({ color: "#f05d5e" })
        .setLngLat(coords[coords.length - 1])
        .addTo(map);

      const bounds = coords.reduce(
        (b, c) => b.extend(c),
        new maplibregl.LngLatBounds(coords[0], coords[0])
      );
      map.fitBounds(bounds, { padding: 40, duration: 0 });
    });

    // Keep the canvas matched to its container (hero banner / layout shifts).
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(ref.current);
    return () => {
      ro.disconnect();
      map.remove();
    };
  }, [samples]);

  return <div className="map" ref={ref} />;
}
