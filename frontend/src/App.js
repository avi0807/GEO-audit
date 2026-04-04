import { useState } from "react";
import { motion } from "framer-motion";
import { CircularProgressbar, buildStyles } from "react-circular-progressbar";
import "react-circular-progressbar/dist/styles.css";
import "./App.css";

export default function App() {
  const [url, setUrl] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const runAudit = async () => {
    if (!url) return;
    setLoading(true);
    setData(null);

    try {
      const res = await fetch("http://localhost:8000/audit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ url }),
      });

      const json = await res.json();
      if(!res.ok){
        alert(`Error: ${json.detail || "Something went wrong"}`);
        return ;
      }
      setData(json);
    } catch (err) {
      alert("Error running audit");
    } finally {
      setLoading(false);
    }
  };

 
  const containerVariant = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: 0.15,
      },
    },
  };


  const cardVariant = {
    hidden: { opacity: 0, y: -30, scale: 0.98 },
    visible: {
      opacity: 1,
      y: 0,
      scale: 1,
      transition: {
        duration: 0.5,
        ease: "easeOut",
      },
    },
  };

  return (
    <div className="app">
      {/* HERO */}
      <motion.div
        className="hero"
        initial={{ opacity: 0, y: -40 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      >
        <h1>GEO Audit</h1>
        <p>Optimize your site for AI search visibility</p>

        <div className="input-row">
          <input
            type="text"
            placeholder="https://example.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
            onClick={runAudit}
          >
            Run Audit
          </motion.button>
        </div>
      </motion.div>

      {/* LOADING */}
      {loading && (
        <motion.p
          className="loading"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        >
          Analyzing your page...
        </motion.p>
      )}

      {/* RESULTS */}
      {data && (
        <motion.div
          className="results"
          variants={containerVariant}
          initial="hidden"
          animate="visible"
        >
          {/* SCORE */}
          <motion.div className="card score-card" variants={cardVariant}>
            <h3 style={{ textAlign: "center", marginBottom: "20px" }}>
              GEO Score
            </h3>

            <div className="score-container">
              <div className="score-circle">
                <CircularProgressbar
                  value={data.geo_scores?.overall}
                  text={`${data.geo_scores?.overall}`}
                  styles={buildStyles({
                    textColor: "#fff",
                    pathColor: "#ff7a00",
                    trailColor: "#333",
                  })}
                />
              </div>

              <div className="score-details">
                <p>Structured Data</p>
                <progress value={data.geo_scores?.structured_data} max="100" />

                <p>Content Clarity</p>
                <progress value={data.geo_scores?.content_clarity} max="100" />

                <p>AI Citation Potential</p>
                <progress value={data.geo_scores?.ai_citation_potential} max="100" />
              </div>
            </div>
          </motion.div>

          {/* METADATA */}
          <motion.div className="card" variants={cardVariant}>
            <h3>Metadata</h3>
            <p><b>Title:</b> {data.page_title}</p>
            <p><b>Description:</b> {data.meta_description}</p>
          </motion.div>

          {/* INSIGHTS */}
          <motion.div className="card" variants={cardVariant}>
            <h3>Insights</h3>
            <ul>
              {data.geo_insights?.map((i, idx) => (
                <li key={idx}>{i}</li>
              ))}
            </ul>
          </motion.div>

          {/* SCHEMA */}
          <motion.div className="card" variants={cardVariant}>
            <h3>Schema Recommendation</h3>
            <pre>
              {JSON.stringify(data.json_ld_recommendation, null, 2)}
            </pre>
          </motion.div>
        </motion.div>
      )}
    </div>
  );
}