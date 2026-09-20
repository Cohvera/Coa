export default function App() {
  const data = {bank: 8635, ar: 59990, ap: 101686, drafts: 50000};
  const cash = data.bank + data.ar + data.drafts - data.ap;
  const qhomeUrl = import.meta.env.VITE_QHOME_URL || `${window.location.protocol}//${window.location.hostname}:8000`;
  return <div style={{padding: '28px', fontFamily: 'Arial'}}>
    <h1>Cohvera Pulse</h1><h2>Q-Home</h2>
    <section style={{padding:'24px', background:'#e8efdf', borderRadius:10, marginBottom:28}}>
      <h2>Elektriciteitsoffertes voor projectbouw</h2>
      <p>Importeer de meetstaat van je klant en maak een prijsvoorstel met je all-in standaardprijzen.</p>
      <a href={qhomeUrl} style={{color:'#234c41', fontWeight:700}}>Open Q-Home Offer Assistant →</a>
    </section>
    <div style={{display:'grid', gridTemplateColumns:'repeat(5,1fr)', gap:10}}>
      <div>Bank<br/><b>€{data.bank}</b></div><div>Klanten<br/><b>€{data.ar}</b></div>
      <div>Leveranciers<br/><b>€{data.ap}</b></div><div>Drafts<br/><b>€{data.drafts}</b></div><div>Cashpositie<br/><b>€{cash}</b></div>
    </div>
  </div>;
}
