import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Logo } from "../components";

const OUTPUT = [
  ["Process overview", "Applications used, inputs, decision points and recorded duration."],
  ["Flowchart", "The whole process at a glance, with decisions as diamonds."],
  ["Steps with screenshots", "Numbered, specific instructions, each with the right screen."],
  ["Exceptions", "Business and system exceptions, plus rules and requirements."],
];

const API_POINTS = [
  ["Bring your own key", "Add your API key in your account. It stays hidden after you save it."],
  ["Pay only for what you use", "Usage is billed by your provider, and every project shows what it cost to run."],
  ["Choose per project", "Keep separate keys for work and personal use, and pick one when you create a project."],
];

export default function LandingPage() {
  const api = useRef<HTMLElement>(null);
  const [apiInView, setApiInView] = useState(false);

  useEffect(() => {
    const el = api.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setApiInView(true);
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setApiInView(true);
        observer.disconnect();
      }
    }, { threshold: 0.35 });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="landing">
      <header className="landing-header">
        <Logo to="/" large />
        <nav aria-label="Main" className="landing-nav">
          <Link to="/login">Log in</Link>
          <Link to="/login?mode=register" className="outline">Get started</Link>
        </nav>
      </header>

      <section id="top" className="hero">
        <div className="hero-copy">
          <h1>Upload the recording.<br />Get the PDD.</h1>
          <p>Pidi turns any screen recording into a complete Process Design Document.</p>
          <div className="hero-actions">
            <Link to="/login?mode=register" className="btn btn-dark btn-lg">Get started</Link>
            <a href="#output" className="btn btn-outline btn-lg">See what you get</a>
          </div>
        </div>
        <div className="hero-art">
          <HeroAnimation />
        </div>
      </section>

      <section id="output" className="band">
        <div className="band-inner">
          <h2 className="section-title" style={{ maxWidth: 640 }}>Everything a PDD needs, already in place.</h2>
          <div className="flow">
            {OUTPUT.map(([title, text], i) => (
              <FlowItem key={title} index={i} title={title} text={text} last={i === OUTPUT.length - 1} />
            ))}
          </div>
        </div>
      </section>

      <section id="api" className="api" ref={api}>
        <div className="api-inner">
          <div className="api-intro">
            <h2 className="section-title">Your API, your data</h2>
            <p>Connect your key once and Pidi uses it for every project. No middleman on your usage.</p>
          </div>
          <div className="api-list">
            {API_POINTS.map(([title, text], i) => (
              <div key={title} className={`api-item rv rv${i + 1}${apiInView ? " on" : ""}`}>
                <span className="num">{String(i + 1).padStart(2, "0")}</span>
                <div><h3>{title}</h3><p>{text}</p></div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="cta-wrap">
        <div className="cta">
          <h2>Stop documenting. Start automating.</h2>
          <p>Turn your next screen recording into a PDD and spend the time on the automation itself.</p>
          <Link to="/login?mode=register" className="btn btn-light btn-lg">Create your first PDD</Link>
        </div>
      </section>

      <footer className="landing-footer">© {new Date().getFullYear()} pidi</footer>
    </div>
  );
}

function FlowItem({ index, title, text, last }: { index: number; title: string; text: string; last: boolean }) {
  return (
    <>
      <div className={`flow-card dc d${index + 1}`}>
        <h3>{title}</h3>
        <p>{text}</p>
      </div>
      {!last && (
        <div className={`flow-arrow a${index + 1}`} aria-hidden="true">
          <span className="track"><span className="dcl" /></span>
          <svg width="8" height="12" viewBox="0 0 8 12" style={{ marginLeft: -2 }}>
            <path d="M1 1l6 5-6 5" fill="none" stroke="var(--dash)" strokeWidth="1.5" />
          </svg>
        </div>
      )}
    </>
  );
}

/** Upload → reading → writing → ready, looping (static on reduced motion). */
function HeroAnimation() {
  return (
    <div className="hero-card" aria-hidden="true">
      <div className="hero-stage">
        <div className="st s1">
          <div className="upload-circle">
            <svg className="pd-bob" width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M5 16v3h14v-3" />
            </svg>
          </div>
          <div className="caption">Upload your video</div>
        </div>
        <div className="st s2">
          <div className="video">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="#F5F3EF"><path d="M8 5.5v13l11-6.5z" /></svg>
          </div>
          <div className="video-bar"><div className="pd-fill" /></div>
          <div className="caption">Reading the process</div>
        </div>
        <div className="st s3">
          <div className="paper">
            <div className="title">Process Design Document</div>
            <div className="mini-flow">
              <span className="box" /><span className="link" /><span className="diamond" />
              <span className="link" /><span className="box" />
            </div>
            {[100, 82, 92, 64, 88].map((w) => <div key={w} className="pd-line" style={{ width: `${w}%` }} />)}
          </div>
          <div className="caption">Writing your PDD</div>
        </div>
        <div className="st s4">
          <div className="pd-pop">
            <svg width="112" height="112" viewBox="0 0 112 112" fill="none" stroke="currentColor" strokeWidth="3"
                 strokeLinecap="round">
              <circle cx="56" cy="56" r="50" />
              <circle cx="40" cy="46" r="3" fill="currentColor" stroke="none" />
              <circle cx="72" cy="46" r="3" fill="currentColor" stroke="none" />
              <path d="M36 66c5 9 12 13 20 13s15-4 20-13" stroke="var(--accent)" />
            </svg>
            <span className="check">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#FFFFFF" strokeWidth="2.4"
                   strokeLinecap="round" strokeLinejoin="round"><path d="m3.5 8.5 3 3 6-7" /></svg>
            </span>
          </div>
          <div className="caption">Your PDD is ready</div>
        </div>
      </div>
    </div>
  );
}
