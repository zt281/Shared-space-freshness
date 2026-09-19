// Disposable two-flow MsQuic experiment. No exchange API, secrets, or real orders.
#include "quic_replica.hpp"
#include "durable_consumer.hpp"
#include <msquic.h>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <thread>
#include <unistd.h>

using namespace quic_demo;
namespace {
Tick now_ms(){return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
void qcheck(QUIC_STATUS s,const char* what){require(QUIC_SUCCEEDED(s),std::string(what)+" status="+std::to_string(s));}
Bytes read_bytes(const std::filesystem::path&p){std::ifstream in(p,std::ios::binary);require(bool(in),"read pinned certificate");return Bytes(std::istreambuf_iterator<char>(in),{});}
std::string replica_name(const std::string& token,int f){return "/tyche-quic-"+token+"-"+std::to_string(f);}
Space::Location source_location(const std::filesystem::path&root,const std::string&token,int f){return{"/tyche-independent-"+token+"-source-"+std::to_string(f),root/("PROTOTYPE-source-"+std::to_string(f)+".bin"),static_cast<std::uint64_t>(100+f)};}
struct App;
struct Conn;
struct Stream {
  App* app;Conn* conn;HQUIC handle=nullptr;bool uni=false;
  std::atomic<bool> done{false};
  Framer framer; // Application worker only.
  std::uint64_t flow=0;
};
struct Conn {
  App* app;HQUIC handle=nullptr;
  std::atomic<bool> pinned{false},connected{false},closing{false},done{false};
  Stream* control=nullptr;
  std::array<Stream*,2> data{};
  std::array<std::uint64_t,2> next{},acked{};
  std::uint64_t generation=0,mask=0;
  std::optional<Words> held_barrier;
};
struct Send {Bytes bytes;QUIC_BUFFER buffer;explicit Send(Bytes b):bytes(std::move(b)),buffer{static_cast<std::uint32_t>(bytes.size()),bytes.data()}{}};
struct App {
  bool source;
  std::filesystem::path root;
  std::string token;
  std::uint16_t port;
  const QUIC_API_TABLE* api=nullptr;
  HQUIC registration=nullptr,configuration=nullptr,listener=nullptr;
  Bytes peer_der;
  std::array<std::unique_ptr<Space>,2> sources;
  std::array<std::unique_ptr<ReplicaSpace>,2> replicas;
  std::mutex objects_mutex,queue_mutex,output_mutex;
  std::condition_variable wake;
  std::vector<std::unique_ptr<Conn>> connections;
  std::vector<std::unique_ptr<Stream>> streams;
  std::deque<std::function<void()>> jobs;
  std::thread worker;
  std::atomic<bool> stopping{false},finish_worker{false};
  std::atomic<std::size_t> borrowed{0},send_bytes{0},max_borrowed{0},max_send{0};
  std::atomic<unsigned> pending_receives{0},slow_ms{0};
  std::atomic<bool> pause_sync{false},at_sync{false};
  static constexpr std::size_t data_limit=4096,send_limit=8192,receive_limit=512*1024,job_limit=64;
  Conn* active=nullptr; // Application worker owns business state below.
  std::uint64_t generation=0,mask=1;
  std::array<std::uint64_t,2> barrier{},epochs{},received{},durable{},visible{},subscription_cursor{};
  bool barrier_seen=false,ready=false,storage_failed=false;
  int crash=0;bool sync_error=false;
  unsigned paused_flow=0;
  bool hold_barrier=false;
  std::uint64_t sent=0,duplicates=0,ignored=0,gaps=0,transport_completions=0;
  std::atomic<std::uint64_t> completions{0};
  std::string failure;

  void log(const std::string& event,const std::string& fields=""){
    std::lock_guard lock(output_mutex);
    std::cout<<"{\"event\":"<<std::quoted(event)<<",\"pid\":"<<getpid()<<",\"mono_ms\":"<<now_ms();
    if(!fields.empty())std::cout<<','<<fields;
    std::cout<<'}'<<std::endl;
  }
  bool enqueue(std::function<void()> job){
    std::lock_guard lock(queue_mutex);
    if(jobs.size()>=job_limit||finish_worker)return false;
    jobs.push_back(std::move(job));wake.notify_all();return true;
  }
  static void peak(std::atomic<std::size_t>&v,std::size_t n){auto old=v.load();while(old<n&&!v.compare_exchange_weak(old,n)){};}
  bool reserve_receive(std::size_t n){
    auto occupied=borrowed.load();
    do {if(n>receive_limit||occupied>receive_limit-n)return false;}
    while(!borrowed.compare_exchange_weak(occupied,occupied+n));
    peak(max_borrowed,occupied+n);return true;
  }
  void shutdown(Conn&c,std::uint64_t reason=1){if(!c.closing.exchange(true))api->ConnectionShutdown(c.handle,QUIC_CONNECTION_SHUTDOWN_FLAG_NONE,reason);}
  void restrict_all(){
    ready=barrier_seen=false;
    if(!source)for(auto&r:replicas)r->restrict();
  }
  void fail(Conn&c,const std::string&why){
    failure=why;log("failure","\"reason\":"+quoted(why));
    if(&c==active&&!source)restrict_all();
    shutdown(c,2);
  }
  static std::string quoted(const std::string&s){std::ostringstream out;out<<std::quoted(s);return out.str();}
  Conn* make_conn(HQUIC handle=nullptr){
    std::lock_guard lock(objects_mutex);require(connections.size()<16,"bounded prototype connection lifetime");
    auto c=std::make_unique<Conn>();c->app=this;c->handle=handle;auto*p=c.get();connections.push_back(std::move(c));return p;
  }
  Stream* make_stream(Conn&c,HQUIC handle,bool uni){
    std::lock_guard lock(objects_mutex);require(streams.size()<64,"bounded prototype stream lifetime");
    auto s=std::make_unique<Stream>();s->app=this;s->conn=&c;s->handle=handle;s->uni=uni;
    auto*p=s.get();streams.push_back(std::move(s));return p;
  }
  Stream* open_stream(Conn&c,bool uni){
    auto*s=make_stream(c,nullptr,uni);
    qcheck(api->StreamOpen(c.handle,uni?QUIC_STREAM_OPEN_FLAG_UNIDIRECTIONAL:QUIC_STREAM_OPEN_FLAG_NONE,stream_cb,s,&s->handle),"StreamOpen");
    qcheck(api->StreamStart(s->handle,QUIC_STREAM_START_FLAG_IMMEDIATE),"StreamStart");return s;
  }
  bool send(Stream&s,Bytes bytes){
    if(s.conn->closing||s.done)return false;
    const auto n=bytes.size();
    if(send_bytes.load()+n>(s.uni?data_limit:send_limit))return false;
    auto*p=new Send(std::move(bytes));send_bytes+=n;peak(max_send,send_bytes.load());
    auto status=api->StreamSend(s.handle,&p->buffer,1,QUIC_SEND_FLAG_NONE,p);
    if(QUIC_FAILED(status)){send_bytes-=n;delete p;throw std::runtime_error("StreamSend status="+std::to_string(status));}
    return true;
  }
  bool send(Stream&s,const Words&w){return send(s,encode(w));}
  void control(Conn&c,const Words&w){require(c.control&&send(*c.control,w),"bounded control send unavailable");}
  static QUIC_STATUS QUIC_API stream_cb(HQUIC,void*ctx,QUIC_STREAM_EVENT*e){
    auto&s=*static_cast<Stream*>(ctx);auto&a=*s.app;
    try {
      switch(e->Type){
      case QUIC_STREAM_EVENT_START_COMPLETE:
        if(QUIC_FAILED(e->START_COMPLETE.Status))a.shutdown(*s.conn,3);
        break;
      case QUIC_STREAM_EVENT_RECEIVE:{
        const auto total=e->RECEIVE.TotalBufferLength;
        if(!total)return QUIC_STATUS_SUCCESS;
        // Default single-pending mode per stream; retain descriptors, not event memory.
        if(e->RECEIVE.BufferCount>64||!a.reserve_receive(total)){
          e->RECEIVE.TotalBufferLength=0;a.shutdown(*s.conn,4);return QUIC_STATUS_SUCCESS;
        }
        std::vector<QUIC_BUFFER> buffers(e->RECEIVE.Buffers,e->RECEIVE.Buffers+e->RECEIVE.BufferCount);
        ++a.pending_receives;
        bool queued=a.enqueue([&a,&s,buffers=std::move(buffers),total]{
          try{
            if(!s.conn->closing&&!a.stopping){
              if(a.slow_ms.load())std::this_thread::sleep_for(std::chrono::milliseconds(a.slow_ms.load()));
              for(const auto&b:buffers)s.framer.feed(std::span(b.Buffer,b.Length),[&](const Words&w){a.message(s,w);});
            }
          }catch(const std::exception&x){a.fail(*s.conn,x.what());}
          // No descriptor/buffer dereference after Complete. Handles stay open until join.
          a.api->StreamReceiveComplete(s.handle,total);a.borrowed-=total;--a.pending_receives;a.wake.notify_all();
        });
        if(!queued){a.borrowed-=total;--a.pending_receives;e->RECEIVE.TotalBufferLength=0;a.shutdown(*s.conn,4);return QUIC_STATUS_SUCCESS;}
        return QUIC_STATUS_PENDING;
      }
      case QUIC_STREAM_EVENT_SEND_COMPLETE:{
        auto*p=static_cast<Send*>(e->SEND_COMPLETE.ClientContext);a.send_bytes-=p->bytes.size();delete p;
        ++a.completions;a.wake.notify_all();break;
      }
      case QUIC_STREAM_EVENT_PEER_SEND_SHUTDOWN:
      case QUIC_STREAM_EVENT_PEER_SEND_ABORTED:
      case QUIC_STREAM_EVENT_PEER_RECEIVE_ABORTED:
        a.shutdown(*s.conn,5);break; // This finite prototype keeps all streams until connection close.
      case QUIC_STREAM_EVENT_SHUTDOWN_COMPLETE:s.done=true;a.wake.notify_all();break;
      default:break;
      }
      return QUIC_STATUS_SUCCESS;
    }catch(...){a.shutdown(*s.conn,6);return QUIC_STATUS_INTERNAL_ERROR;}
  }
  static QUIC_STATUS QUIC_API conn_cb(HQUIC,void*ctx,QUIC_CONNECTION_EVENT*e){
    auto&c=*static_cast<Conn*>(ctx);auto&a=*c.app;
    try{
      switch(e->Type){
      case QUIC_CONNECTION_EVENT_PEER_CERTIFICATE_RECEIVED:{
        auto*leaf=reinterpret_cast<const QUIC_BUFFER*>(e->PEER_CERTIFICATE_RECEIVED.Certificate);
        if(!leaf||!leaf->Buffer||leaf->Length!=a.peer_der.size()||std::memcmp(leaf->Buffer,a.peer_der.data(),leaf->Length))return QUIC_STATUS_BAD_CERTIFICATE;
        c.pinned=true;break;
      }
      case QUIC_CONNECTION_EVENT_CONNECTED:
        if(!c.pinned)return QUIC_STATUS_BAD_CERTIFICATE;
        c.connected=true;
        if(!a.enqueue([&a,&c]{a.connected(c);})){a.shutdown(c,4);}
        break;
      case QUIC_CONNECTION_EVENT_PEER_STREAM_STARTED:{
        auto*s=a.make_stream(c,e->PEER_STREAM_STARTED.Stream,(e->PEER_STREAM_STARTED.Flags&QUIC_STREAM_OPEN_FLAG_UNIDIRECTIONAL)!=0);
        a.api->SetCallbackHandler(s->handle,reinterpret_cast<void*>(stream_cb),s);break;
      }
      case QUIC_CONNECTION_EVENT_SHUTDOWN_INITIATED_BY_TRANSPORT:
        a.log("transport_shutdown","\"status\":"+std::to_string(e->SHUTDOWN_INITIATED_BY_TRANSPORT.Status));c.closing=true;break;
      case QUIC_CONNECTION_EVENT_SHUTDOWN_INITIATED_BY_PEER:c.closing=true;break;
      case QUIC_CONNECTION_EVENT_SHUTDOWN_COMPLETE:c.connected=false;c.done=true;c.closing=true;a.wake.notify_all();break;
      default:break;
      }
      return QUIC_STATUS_SUCCESS;
    }catch(...){a.shutdown(c,6);return QUIC_STATUS_INTERNAL_ERROR;}
  }
  static QUIC_STATUS QUIC_API listener_cb(HQUIC,void*ctx,QUIC_LISTENER_EVENT*e){
    auto&a=*static_cast<App*>(ctx);
    if(e->Type!=QUIC_LISTENER_EVENT_NEW_CONNECTION)return QUIC_STATUS_SUCCESS;
    if(a.stopping)return QUIC_STATUS_CONNECTION_REFUSED;
    try{
      auto*c=a.make_conn(e->NEW_CONNECTION.Connection);
      a.api->SetCallbackHandler(c->handle,reinterpret_cast<void*>(conn_cb),c);
      auto st=a.api->ConnectionSetConfiguration(c->handle,a.configuration);
      if(QUIC_FAILED(st)){c->handle=nullptr;c->done=true;}
      return st;
    }catch(...){return QUIC_STATUS_CONNECTION_REFUSED;}
  }
  App(bool server,const std::filesystem::path&dir,std::string t,bool create,std::uint16_t p,
      const std::filesystem::path&certdir,const std::filesystem::path&pin)
      :source(server),root(dir),token(std::move(t)),port(p),peer_der(read_bytes(pin)){
    require(!peer_der.empty()&&peer_der.size()<16384,"bounded pinned leaf DER");
    for(int f=1;f<=2;++f){
      if(source){
        auto loc=source_location(root,token,f);
        if(create){Space initializer(loc,Space::Access::create);}
        sources[f-1]=std::make_unique<Space>(loc,Space::Access::publisher);
        sources[f-1]->replace(now_ms());
      }else{
        replicas[f-1]=std::make_unique<ReplicaSpace>(root,replica_name(token,f),100+f,true,create,0x510000000000ULL+f*0x100000);
        durable[f-1]=visible[f-1]=received[f-1]=replicas[f-1]->attachment().head;
      }
    }
    qcheck(MsQuicOpen2(&api),"MsQuicOpen2");
    QUIC_REGISTRATION_CONFIG reg{"tyche-quic-prototype",QUIC_EXECUTION_PROFILE_LOW_LATENCY};
    qcheck(api->RegistrationOpen(&reg,&registration),"RegistrationOpen");
    QUIC_SETTINGS settings{};
    settings.IsSet.IdleTimeoutMs=TRUE;settings.IdleTimeoutMs=5000;
    settings.IsSet.HandshakeIdleTimeoutMs=TRUE;settings.HandshakeIdleTimeoutMs=3000;
    settings.IsSet.PeerBidiStreamCount=TRUE;settings.PeerBidiStreamCount=2;
    settings.IsSet.PeerUnidiStreamCount=TRUE;settings.PeerUnidiStreamCount=4;
    settings.IsSet.StreamRecvWindowDefault=TRUE;settings.StreamRecvWindowDefault=4096;
    settings.IsSet.ConnFlowControlWindow=TRUE;settings.ConnFlowControlWindow=16384;
    settings.IsSet.DatagramReceiveEnabled=TRUE;settings.DatagramReceiveEnabled=FALSE;
    settings.IsSet.SendBufferingEnabled=TRUE;settings.SendBufferingEnabled=FALSE;
    settings.IsSet.ServerResumptionLevel=TRUE;settings.ServerResumptionLevel=QUIC_SERVER_NO_RESUME;
    // StreamMultiReceive is a preview ABI field; with the stable API it remains its FALSE default.
    const char alpn_text[]="tyche-quic-prototype-v1";
    QUIC_BUFFER alpn{sizeof(alpn_text)-1,reinterpret_cast<std::uint8_t*>(const_cast<char*>(alpn_text))};
    qcheck(api->ConfigurationOpen(registration,&alpn,1,&settings,sizeof(settings),nullptr,&configuration),"ConfigurationOpen");
    auto key=(certdir/(source?"server.key":"client.key")).string();
    auto cert=(certdir/(source?"server.pem":"client.pem")).string();auto ca=(certdir/"ca.pem").string();
    QUIC_CERTIFICATE_FILE files{key.c_str(),cert.c_str()};QUIC_CREDENTIAL_CONFIG cred{};
    cred.Type=QUIC_CREDENTIAL_TYPE_CERTIFICATE_FILE;cred.CertificateFile=&files;cred.CaCertificateFile=ca.c_str();
    cred.Flags=static_cast<QUIC_CREDENTIAL_FLAGS>(QUIC_CREDENTIAL_FLAG_USE_TLS_BUILTIN_CERTIFICATE_VALIDATION|
      QUIC_CREDENTIAL_FLAG_SET_CA_CERTIFICATE_FILE|QUIC_CREDENTIAL_FLAG_INDICATE_CERTIFICATE_RECEIVED|
      QUIC_CREDENTIAL_FLAG_USE_PORTABLE_CERTIFICATES|(source?QUIC_CREDENTIAL_FLAG_REQUIRE_CLIENT_AUTHENTICATION:QUIC_CREDENTIAL_FLAG_CLIENT));
    if(!source&&!std::filesystem::exists(key)){cred.Type=QUIC_CREDENTIAL_TYPE_NONE;cred.CertificateFile=nullptr;}
    qcheck(api->ConfigurationLoadCredential(configuration,&cred),"ConfigurationLoadCredential");
    worker=std::thread([this]{run();});
    if(source){
      qcheck(api->ListenerOpen(registration,listener_cb,this,&listener),"ListenerOpen");
      QUIC_ADDR addr{};QuicAddrSetFamily(&addr,QUIC_ADDRESS_FAMILY_INET);QuicAddrSetPort(&addr,port);QuicAddrSetToLoopback(&addr);
      qcheck(api->ListenerStart(listener,&alpn,1,&addr),"ListenerStart");
    }
    log("started","\"source\":"+std::string(source?"true":"false")+",\"port\":"+std::to_string(port));
  }
  void connect(){
    require(!source&&!storage_failed,"receiver may connect only with healthy storage");
    if(active&&!active->done)throw std::runtime_error("previous connection has not shut down");
    restrict_all();auto*c=make_conn();active=c;
    qcheck(api->ConnectionOpen(registration,conn_cb,c,&c->handle),"ConnectionOpen");
    qcheck(api->ConnectionStart(c->handle,configuration,QUIC_ADDRESS_FAMILY_INET,"127.0.0.1",port),"ConnectionStart");
  }
  void connected(Conn&c){
    log("authenticated","\"peer_node\":"+std::to_string(source?2:1));
    if(!source){require(active==&c,"unexpected receiver connection");c.control=open_stream(c,false);subscribe(mask);}
  }
  void subscribe(std::uint64_t selected){
    require(!source&&active&&active->connected&&!active->closing&&selected&&selected<=3,"subscription prerequisites");
    restrict_all();mask=selected;++generation;
    for(int i=0;i<2;++i)durable[i]=visible[i]=received[i]=replicas[i]->attachment().head;
    subscription_cursor=durable;
    control(*active,Words{protocol,1,generation,mask,101,102,durable[0],durable[1],2});
  }
  void maybe_ready(){
    if(!barrier_seen||storage_failed||!active||active->closing)return;
    for(int i=0;i<2;++i)if(mask&(1ULL<<i)){
      if(visible[i]<barrier[i]||!visible[i]||replicas[i]->read(now_ms()).record.epoch!=epochs[i])return;
    }
    if(!ready){for(int i=0;i<2;++i)if(mask&(1ULL<<i))replicas[i]->activate();ready=true;log("subscription_ready","\"g\":"+std::to_string(generation));}
  }
  void message(Stream&s,const Words&w){
    auto&c=*s.conn;
    require(c.connected&&c.pinned&&!c.closing,"data before authenticated live connection");
    require(w.size()>=2&&w[0]==protocol,"wire protocol/version");
    if(source){
      require(!s.uni,"source expects bidirectional control only");
      if(!c.control)c.control=&s;
      require(c.control==&s,"one control stream per connection");
      if(w[1]==1){
        require(w.size()==9&&w[8]==2&&w[2]>c.generation&&w[3]>0&&w[3]<=3&&w[4]==101&&w[5]==102,"subscription identity/generation");
        // Fixed authenticated peer 2 is authorized for either of the two test objects only.
        c.generation=w[2];c.mask=w[3];
        Words b{protocol,2,c.generation,c.mask,101,102,0,0,0,0,1};
        for(int i=0;i<2;++i){auto a=sources[i]->attachment();require(w[6+i]<=a.head,"replica cursor ahead of authority");c.next[i]=w[6+i]+1;b[6+i]=a.head;b[8+i]=a.authority;
          if((c.mask&(1ULL<<i))&&!c.data[i])c.data[i]=open_stream(c,true);
        }
        c.held_barrier=b;
        log("barrier_captured","\"g\":"+std::to_string(c.generation));
      }else if(w[1]==4){
        require(w.size()==9&&w[8]==2&&w[3]>=1&&w[3]<=2&&w[4]==100+w[3],"progress identity");
        if(w[2]!=c.generation){++ignored;return;}
        require(w[7]<=w[6]&&w[6]<=w[5]&&w[5]<=sources[w[3]-1]->attachment().head,"invalid progress watermarks");
        c.acked[w[3]-1]=std::max(c.acked[w[3]-1],w[6]);
      }else throw std::runtime_error("unexpected source control message");
      return;
    }
    require(&c==active,"stale receiver connection");
    if(w[1]==2){
      require(!s.uni&&&s==c.control&&w.size()==11&&w[10]==1&&w[4]==101&&w[5]==102,"barrier identity/stream");
      if(w[2]!=generation){++ignored;return;}
      require(w[3]==mask,"barrier dependency set mismatch");
      // Independent streams may deliver later committed data before this barrier.
      for(int i=0;i<2;++i){barrier[i]=w[6+i];epochs[i]=w[8+i];require(barrier[i]>=subscription_cursor[i]&&epochs[i]>0,"barrier regressed");}
      barrier_seen=true;maybe_ready();return;
    }
    require(w[1]==3&&w.size()==5+record_words&&s.uni&&w[3]>=1&&w[3]<=2&&w[4]==100+w[3],"data identity/stream");
    if(!s.flow)s.flow=w[3];
    require(s.flow==w[3],"flow moved between streams");
    if(w[2]!=generation){++ignored;return;}
    const auto i=static_cast<std::size_t>(w[3]-1);require(mask&(1ULL<<i),"unsubscribed data");
    auto event=record_from(w,5);
    if(event.sequence>durable[i]+1){++gaps;log("gap","\"flow\":"+std::to_string(i+1));subscribe(mask);return;}
    received[i]=std::max(received[i],event.sequence);
    const int point=crash;crash=0;bool fail_sync=sync_error;sync_error=false;
    try{
      bool fresh=replicas[i]->accept(event,point,fail_sync,[&]{
        if(pause_sync){at_sync=true;log("before_sync","\"flow\":"+std::to_string(i+1)+",\"R\":"+std::to_string(received[i])+",\"D\":"+std::to_string(durable[i])+",\"V\":"+std::to_string(visible[i]));
          while(pause_sync&&!stopping)std::this_thread::sleep_for(std::chrono::milliseconds(2));
          at_sync=false;
        }
      });
      if(!fresh)++duplicates;
      durable[i]=visible[i]=replicas[i]->attachment().head;
    }catch(...){storage_failed=true;restrict_all();throw;}
    control(c,Words{protocol,4,generation,i+1,101+i,received[i],durable[i],visible[i],2});
    maybe_ready();
    log("replica_progress","\"g\":"+std::to_string(generation)+",\"flow\":"+std::to_string(i+1)+",\"R\":"+std::to_string(received[i])+",\"D\":"+std::to_string(durable[i])+",\"V\":"+std::to_string(visible[i]));
  }
  Words data_words(Conn&c,int i,std::uint64_t seq){
    auto batch=sources[i]->read_after(seq-1,1,now_ms());
    require(batch.complete&&batch.events.size()==1&&batch.events[0].sequence==seq,"source complete committed event");
    Words w{protocol,3,c.generation,static_cast<std::uint64_t>(i+1),static_cast<std::uint64_t>(101+i)};
    auto r=record_words_of(batch.events[0]);w.insert(w.end(),r.begin(),r.end());return w;
  }
  void pump(){
    if(stopping)return;
    if(!source){if(active&&active->closing&&ready)restrict_all();return;}
    std::vector<Conn*> list;{std::lock_guard lock(objects_mutex);for(auto&c:connections)list.push_back(c.get());}
    for(auto*c:list)if(c->connected&&!c->closing&&c->generation){
      if(c->held_barrier&&!hold_barrier){control(*c,*c->held_barrier);c->held_barrier.reset();}
      for(int i=0;i<2;++i)if((c->mask&(1ULL<<i))&&paused_flow!=static_cast<unsigned>(i+1)){
        if(c->next[i]<=sources[i]->attachment().head&&send(*c->data[i],data_words(*c,i,c->next[i]))){++c->next[i];++sent;}
      }
    }
  }
  void run(){
    while(!finish_worker){
      std::function<void()> job;
      {std::unique_lock lock(queue_mutex);if(jobs.empty())wake.wait_for(lock,std::chrono::milliseconds(1));if(!jobs.empty()){job=std::move(jobs.front());jobs.pop_front();}}
      try{if(job)job();pump();}catch(const std::exception&e){failure=e.what();log("worker_error","\"reason\":"+quoted(failure));if(!source&&active)fail(*active,failure);}
    }
  }
  void status(std::uint64_t request){
    std::ostringstream out;out<<"\"request\":"<<request<<",\"g\":"<<generation<<",\"mask\":"<<mask<<",\"ready\":"<<(ready?"true":"false")
      <<",\"connected\":"<<((active&&active->connected&&!active->closing)?"true":"false")<<",\"closed\":"<<((!active||active->done)?"true":"false")
      <<",\"failure\":"<<quoted(failure)<<",\"storage_failed\":"<<(storage_failed?"true":"false")<<",\"duplicates\":"<<duplicates<<",\"ignored\":"<<ignored<<",\"gaps\":"<<gaps
      <<",\"sent\":"<<sent<<",\"send_complete\":"<<completions<<",\"send_bytes\":"<<send_bytes<<",\"max_send_bytes\":"<<max_send
      <<",\"borrowed_bytes\":"<<borrowed<<",\"max_borrowed_bytes\":"<<max_borrowed<<",\"flows\":[";
    for(int i=0;i<2;++i){if(i)out<<',';auto a=source?sources[i]->attachment():replicas[i]->attachment();
      auto v=source?sources[i]->read(now_ms()):replicas[i]->read(now_ms());
      out<<"{\"id\":"<<a.identity<<",\"head\":"<<a.head<<",\"epoch\":"<<v.record.epoch<<",\"authority\":"<<v.authority<<",\"address\":"<<a.address
         <<",\"time\":"<<v.record.verified_time<<",\"provider_generation\":"<<v.provider_generation<<",\"validity\":"<<quoted(label(v.validity))<<",\"R\":"<<received[i]<<",\"D\":"<<durable[i]<<",\"V\":"<<visible[i]<<'}';}
    out<<']';log("status",out.str());
  }
  void command(const std::string&line){
    std::istringstream in(line);std::uint64_t request;std::string op;require(bool(in>>request>>op),"command syntax");
    if(op=="release_sync"){pause_sync=false;log("ack","\"request\":"+std::to_string(request));return;}
    if(op=="slow"){unsigned n;require(bool(in>>n)&&n<=1000,"bounded receive delay");slow_ms=n;log("ack","\"request\":"+std::to_string(request));return;}
    if(op=="gate_sync"){pause_sync=true;log("ack","\"request\":"+std::to_string(request));return;}
    require(enqueue([this,line,request]{
      try{
        std::istringstream args(line);std::uint64_t req;std::string action;args>>req>>action;
        if(action=="status"){status(request);return;}
        if(action=="connect")connect();
        else if(action=="subscribe"){std::uint64_t selected;require(bool(args>>selected),"subscribe mask");subscribe(selected);}
        else if(action=="disconnect"){require(active,"receiver active connection");restrict_all();shutdown(*active);}
        else if(action=="arm"){require(!source&&bool(args>>crash)&&crash>=1&&crash<=4,"crash point 1..4");}
        else if(action=="sync_error"){require(!source,"receiver sync seam");sync_error=true;}
        else if(action=="pause_flow"){require(source&&bool(args>>paused_flow)&&paused_flow<=2,"pause source flow");}
        else if(action=="hold_barrier"){unsigned n;require(source&&bool(args>>n)&&n<=1,"hold barrier seam");hold_barrier=n;}
        else if(action=="publish"){
          int f,n;require(source&&bool(args>>f>>n)&&f>=1&&f<=2&&n>0&&n<=10000,"bounded source publish");
          for(int k=0;k<n;++k){sources[f-1]->prepare(now_ms());require(sources[f-1]->publish(now_ms()),"source publication rejected");}
        }else if(action=="inject"){
          int f;std::uint64_t seq;std::string kind;require(source&&bool(args>>f>>seq>>kind)&&f>=1&&f<=2,"inject source frame");
          Conn*c=nullptr;{std::lock_guard lock(objects_mutex);for(auto&candidate:connections)if(candidate->connected&&!candidate->closing&&candidate->generation)c=candidate.get();}
          require(c&&c->data[f-1],"subscribed injection stream");auto w=data_words(*c,f-1,seq);
          if(kind=="reset"){
            qcheck(api->StreamShutdown(c->data[f-1]->handle,QUIC_STREAM_SHUTDOWN_FLAG_ABORT,7),"injected stream reset");
            log("ack","\"request\":"+std::to_string(request));return;
          }
          if(kind=="old")--w[2];
          if(kind=="conflict"){auto event=record_from(w,5);++event.record.price;event.record.checksum=checksum(event.record);event=Space::proposal(event.sequence,event.record);auto r=record_words_of(event);w.resize(5);w.insert(w.end(),r.begin(),r.end());}
          auto bytes=encode(w);if(kind=="half")bytes.resize(bytes.size()/2);
          if(kind=="oversize")bytes=Bytes{0,0,16,0};
          require(send(*c->data[f-1],std::move(bytes)),"inject bounded send");
        }else throw std::runtime_error("unknown command");
        log("ack","\"request\":"+std::to_string(request));
      }catch(const std::exception&e){log("command_error","\"request\":"+std::to_string(request)+",\"reason\":"+quoted(e.what()));}
    }),"command queue bounded");
  }
  void close(){
    stopping=true;pause_sync=false;
    if(listener){api->ListenerStop(listener);api->ListenerClose(listener);listener=nullptr;}
    std::vector<Conn*> list;{std::lock_guard lock(objects_mutex);for(auto&c:connections)if(c->handle)list.push_back(c.get());}
    for(auto*c:list)shutdown(*c);
    auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(8);
    for(;;){bool drained=true;for(auto*c:list)drained&=c->done.load();
      {std::lock_guard lock(queue_mutex);drained&=jobs.empty();}
      if(drained&&pending_receives==0&&send_bytes==0)break;
      require(std::chrono::steady_clock::now()<deadline,"QUIC shutdown did not drain");std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    finish_worker=true;wake.notify_all();worker.join();
    if(!source)restrict_all();
    for(auto&s:streams)if(s->handle){require(s->done,"stream close before shutdown complete");api->StreamClose(s->handle);}
    for(auto*c:list)api->ConnectionClose(c->handle);
    if(listener)api->ListenerClose(listener);
    api->ConfigurationClose(configuration);api->RegistrationClose(registration);MsQuicClose(api);
    log("shutdown_drained","\"pending_receives\":0,\"send_bytes\":0");
  }
};

int consumer(int argc,char**argv){
  require(argc==9,"consumer ROOT TOKEN create|open FLOW CHECKPOINT ADDRESS");
  const int flow=std::stoi(argv[5]);require(flow>=1&&flow<=2,"consumer flow");
  ReplicaSpace space(argv[2],replica_name(argv[3],flow),100+flow,false,false,std::stoull(argv[8],nullptr,0));
  DurableConsumer c(space,argv[6],std::stoull(argv[7]),std::string(argv[4])=="create");
  std::optional<Consumer::RecoveryTicket> ticket;
  auto reply=[&](std::uint64_t request,bool ok,const std::string&result,Tick tick){
    auto s=c.status(tick);auto a=space.attachment();const auto&saved=c.saved();
    std::cout<<"{\"event\":\"consumer\",\"request\":"<<request<<",\"tick\":"<<tick<<",\"ok\":"<<(ok?"true":"false")<<",\"result\":"<<std::quoted(result)<<",\"address\":"<<a.address
      <<",\"cursor\":"<<s.cursor<<",\"head\":"<<s.head<<",\"allowed\":"<<(s.allowed?"true":"false")<<",\"validity\":"<<std::quoted(label(s.source.validity))
      <<",\"provider_generation\":"<<s.source.provider_generation<<",\"quantity_sum\":"<<saved.quantity_sum<<",\"price_sum\":"<<saved.price_sum
      <<",\"chain\":"<<saved.chain<<",\"stopped\":"<<saved.stopped<<",\"intent_outcome\":"<<saved.intent_outcome<<",\"error\":"<<std::quoted(c.error())<<'}'<<std::endl;
  };
  reply(0,true,"attached",now_ms());std::string line;
  while(std::getline(std::cin,line)){
    std::uint64_t req;std::string op;Tick tick;std::istringstream in(line);require(bool(in>>req>>op>>tick),"consumer command");
    if(op=="quit")return 0;
    bool ok=true;std::string result;std::vector<Change>events;
    if(op=="consume")ok=c.consume(tick,10000,events);
    else if(op=="ticket")ticket=c.recovery_ticket(tick);
    else if(op=="reconcile")ok=ticket&&c.reconcile(*ticket,tick);
    else if(op=="stop")c.stop();else if(op=="resume")c.resume();
    else if(op=="issue")ok=c.issue(tick);else if(op=="execute")result=c.execute(tick);
    else require(op=="status","consumer command known");
    reply(req,ok,result,tick);
  }
  return 0;
}
}
int main(int argc,char**argv){
  try{
    require(argc>=2,"worker role");std::string role=argv[1];
    if(role=="consumer")return consumer(argc,argv);
    if(role=="unlink"){
      require(argc==4,"unlink ROOT TOKEN");for(int f=1;f<=2;++f){ReplicaSpace::unlink(replica_name(argv[3],f));try{Space::unlink_named(source_location(argv[2],argv[3],f));}catch(...){}}
      return 0;
    }
    require(argc==8&&(role=="source"||role=="receiver"),"quic_worker source|receiver ROOT TOKEN create|open PORT CERTDIR PIN_DER");
    auto*app=new App(role=="source",argv[2],argv[3],std::string(argv[4])=="create",static_cast<std::uint16_t>(std::stoul(argv[5])),argv[6],argv[7]);
    std::string line;while(std::getline(std::cin,line)){if(line=="quit")break;app->command(line);}
    app->close();delete app;return 0;
  }catch(const std::exception&e){std::cerr<<"PROTOTYPE_ERROR "<<e.what()<<std::endl;_exit(1);}
}
