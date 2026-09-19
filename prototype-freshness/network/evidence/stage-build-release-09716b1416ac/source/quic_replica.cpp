#include "quic_replica.hpp"
#include "diagnostic_trace.hpp"
#include <cerrno>
#include <fcntl.h>
#include <fstream>
#include <new>
#include <poll.h>
#include <pthread.h>
#include <sstream>
#include <system_error>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace quic_demo {
namespace {
constexpr std::uint64_t magic = 0x54595152504c3031ULL;
void check(bool ok, const char* what) {
  if (!ok) throw std::system_error(errno, std::generic_category(), what);
}
std::uint64_t start_of(int pid) {
  std::ifstream in("/proc/"+std::to_string(pid)+"/stat");
  std::string line, field;
  require(static_cast<bool>(std::getline(in,line)),"read provider process identity");
  auto end=line.rfind(')'); require(end!=std::string::npos,"provider process stat");
  std::istringstream fields(line.substr(end+1));
  for(int i=3;i<=22;++i) require(static_cast<bool>(fields>>field),"provider process fields");
  return std::stoull(field);
}
bool exited(int pid, std::uint64_t start) {
  if(!pid) return true;
  int fd=static_cast<int>(syscall(SYS_pidfd_open,pid,0));
  if(fd<0) return errno==ESRCH;
  pollfd p{fd,POLLIN,0}; int n;
  do { n=poll(&p,1,0); } while(n<0&&errno==EINTR);
  bool dead=n>0&&(p.revents&POLLIN);
  if(!dead&&n>=0) { try { dead=start_of(pid)!=start; } catch(...) {} }
  close(fd); return dead;
}
void sync_file(int fd) {
  int n; do { n=fdatasync(fd); } while(n<0&&errno==EINTR);
  check(n==0,"replica fdatasync");
}
void io(int fd, std::uint8_t* bytes, std::size_t size, off_t at, bool write) {
  std::size_t done=0;
  while(done<size) {
    ssize_t n=write?pwrite(fd,bytes+done,size-done,at+done):pread(fd,bytes+done,size-done,at+done);
    if(n<0&&errno==EINTR) continue;
    if(n<0) check(false,write?"replica pwrite":"replica pread");
    require(n>0,"incomplete replica record I/O"); done+=static_cast<std::size_t>(n);
  }
}
}
struct ReplicaSpace::Shared {
  std::uint64_t magic=0, layout=1, bytes=0, identity=0, device=0, inode=0;
  pthread_mutex_t mutex;
  int pid=0;
  std::uint64_t start=0, head=0, generation=0;
  bool blocked=true, damaged=false;
  Record record{};
  std::array<Change,8> ring{};
};
class ReplicaSpace::Guard {
  Shared& s;
public:
  explicit Guard(ReplicaSpace& owner):s(*owner.shared) {
    timespec until{}; check(clock_gettime(CLOCK_REALTIME,&until)==0,"replica lock clock"); until.tv_sec+=5;
    int n=pthread_mutex_timedlock(&s.mutex,&until);
    if(n==EOWNERDEAD) {
      s.blocked=true; ++s.generation;
      n=pthread_mutex_consistent(&s.mutex);
    }
    if(n) throw std::system_error(n,std::generic_category(),"replica shared mutex");
  }
  ~Guard(){pthread_mutex_unlock(&s.mutex);}
};
ReplicaSpace::ReplicaSpace(const std::filesystem::path& root,const std::string& region_name,
                          std::uint64_t identity,bool provide,bool create,std::uintptr_t address)
    : writer(provide),log_id(identity),name(region_name) {
  require(identity&&name.starts_with("/tyche-quic-")&&name.find('/',1)==std::string::npos,
          "replica prototype identity/name");
  require(!create||provide,"only provider creates replica");
  bool created=false;
  try {
    region=shm_open(name.c_str(),O_RDWR|(create?O_CREAT|O_EXCL:0),0600);
    check(region>=0,"open replica shared region"); created=create;
    check(flock(region,(create?LOCK_EX:LOCK_SH)|LOCK_NB)==0,"replica initialization lease");
    if(create) check(ftruncate(region,sizeof(Shared))==0,"size replica region");
    struct stat st{}; check(fstat(region,&st)==0,"stat replica region");
    require(st.st_size==sizeof(Shared),"replica layout size");
    void* memory=mmap(reinterpret_cast<void*>(address),sizeof(Shared),PROT_READ|PROT_WRITE,
                      MAP_SHARED|(address?MAP_FIXED_NOREPLACE:0),region,0);
    check(memory!=MAP_FAILED,"map replica region"); shared=static_cast<Shared*>(memory);
    if(create) {
      shared=new(memory) Shared{};
      pthread_mutexattr_t attr; int n=pthread_mutexattr_init(&attr);
      if(!n)n=pthread_mutexattr_setpshared(&attr,PTHREAD_PROCESS_SHARED);
      if(!n)n=pthread_mutexattr_setrobust(&attr,PTHREAD_MUTEX_ROBUST);
      if(!n)n=pthread_mutex_init(&shared->mutex,&attr);
      pthread_mutexattr_destroy(&attr);
      if(n)throw std::system_error(n,std::generic_category(),"replica mutex init");
    }
    auto path=root/("PROTOTYPE-replica-"+std::to_string(identity)+".bin");
    journal=open(path.c_str(),(provide?O_RDWR:O_RDONLY)|O_CLOEXEC|(create?O_CREAT|O_EXCL:0),0600);
    check(journal>=0,"open replica journal"); check(fstat(journal,&st)==0,"stat replica journal");
    if(create) {
      shared->layout=1; shared->bytes=sizeof(Shared);shared->identity=identity;
      shared->device=st.st_dev;shared->inode=st.st_ino;shared->magic=magic;
      sync_file(journal);
      int dir=open(root.c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC);check(dir>=0,"replica directory");
      int n=fsync(dir);int e=errno;close(dir);errno=e;check(n==0,"replica directory fsync");
    }
    require(shared->magic==magic&&shared->layout==1&&shared->bytes==sizeof(Shared)&&
            shared->identity==identity&&shared->device==static_cast<std::uint64_t>(st.st_dev)&&
            shared->inode==static_cast<std::uint64_t>(st.st_ino),"replica identity/layout binding");
    if(provide) {
      check(flock(journal,LOCK_EX|LOCK_NB)==0,"replica single provider lease");
      Guard guard(*this);
      require(exited(shared->pid,shared->start),"old replica provider exit unconfirmed");
      shared->blocked=true; ++shared->generation;
      require(!shared->damaged,"replica storage/conflict failure requires investigation");
      require(st.st_size>=0&&st.st_size%disk_bytes==0,"retain incomplete replica journal tail");
      const auto head=static_cast<std::uint64_t>(st.st_size/disk_bytes);
      require(head>=shared->head,"replica durable prefix regressed");
      std::uint64_t epoch=0;
      std::array<Change,8> recovered{};Change last{};
      for(std::uint64_t seq=1;seq<=head;++seq) {
        auto e=load(seq);require(e.record.epoch>=epoch,"replica epoch regressed");
        epoch=e.record.epoch;recovered[(seq-1)%recovered.size()]=e;last=e;
      }
      sync_file(journal); // Full process-crash tail becomes a durable prefix before use.
      shared->ring=recovered;shared->head=head;
      if(head)shared->record=last.record;
      shared->pid=getpid();shared->start=start_of(getpid());
    }
    check(flock(region,LOCK_UN)==0,"release replica initialization lease");
  }catch(...) {
    if(shared)munmap(shared,sizeof(Shared));
    shared=nullptr;
    if(journal>=0)close(journal);
    journal=-1;
    if(region>=0)close(region);
    region=-1;
    if(created)shm_unlink(name.c_str());
    throw;
  }
}
ReplicaSpace::~ReplicaSpace(){if(journal>=0)close(journal);if(shared)munmap(shared,sizeof(Shared));if(region>=0)close(region);}
ReadableSpace::Attachment ReplicaSpace::attachment(){Guard g(*this);return{log_id,shared->record.epoch,shared->head,shared->start,shared->pid,reinterpret_cast<std::uintptr_t>(shared)};}
void ReplicaSpace::unlink(const std::string& n){require(n.starts_with("/tyche-quic-")&&n.find('/',1)==std::string::npos,"replica unlink namespace");if(shm_unlink(n.c_str())!=0&&errno!=ENOENT)check(false,"unlink replica region");}
Change ReplicaSpace::load(std::uint64_t seq) {
  require(seq>0&&seq<=static_cast<std::uint64_t>(std::numeric_limits<off_t>::max()/disk_bytes),"replica sequence/offset");
  Bytes bytes(disk_bytes);io(journal,bytes.data(),bytes.size(),static_cast<off_t>((seq-1)*disk_bytes),false);
  Words words;Framer framer;framer.feed(bytes,[&](const Words&w){words=w;});
  require(!framer.pending()&&words.size()==2+record_words&&words[0]==protocol&&words[1]==log_id,"replica disk identity");
  auto e=record_from(words,2);require(e.sequence==seq,"replica disk sequence");return e;
}
void ReplicaSpace::install(const Change&e){shared->ring[(e.sequence-1)%shared->ring.size()]=e;shared->record=e.record;shared->head=e.sequence;}
View ReplicaSpace::view(Tick now)const {
  const auto&r=shared->record;Validity v=Validity::valid;
  Tick age=now>=r.verified_time?now-r.verified_time:0;
  if(shared->damaged||r.checksum!=checksum(r))v=Validity::damaged;
  else if(shared->blocked||!shared->head||r.gap)v=Validity::gap;
  else if(!r.time_known||now<r.verified_time)v=Validity::unknown;
  else if(age>=expiry_age)v=Validity::expired;
  else if(age>=warning_age)v=Validity::warning;
  return{r,r.epoch,0,shared->damaged,v,age,shared->generation};
}
View ReplicaSpace::read(Tick now){Guard g(*this);return view(now);}
Changes ReplicaSpace::read_after(std::uint64_t cursor,std::size_t budget,Tick now) {
  if(budget)diagnostic::mark("replica_read_begin",log_id,0,cursor+1,budget);
  Guard g(*this);
  if(budget)diagnostic::mark("replica_read_locked",log_id,0,cursor+1,budget,shared->head);
  Changes out{view(now),shared->head,{},0,!shared->damaged};
  if(cursor>out.head){out.complete=false;return out;}
  for(auto seq=cursor+1;seq<=out.head&&out.events.size()<budget;++seq) {
    try {
      Change e;
      if(out.head-seq<shared->ring.size())e=shared->ring[(seq-1)%shared->ring.size()];
      else {diagnostic::mark("replica_history_read_begin",log_id,0,seq);e=load(seq);++out.from_journal;diagnostic::mark("replica_history_read_end",log_id,e.record.epoch,seq);}
      require(e.sequence==seq&&Space::proposal(seq,e.record).seal==e.seal,"replica history seal");out.events.push_back(e);
    }catch(...){shared->damaged=shared->blocked=true;++shared->generation;out.complete=false;out.events.clear();out.latest=view(now);break;}
  }
  if(budget)diagnostic::mark("replica_read_end",log_id,0,cursor+1,budget,out.head,out.events.size());
  return out;
}
void ReplicaSpace::restrict(bool damaged){Guard g(*this);require(writer&&shared->pid==getpid(),"replica provider authority");shared->blocked=true;shared->damaged|=damaged;++shared->generation;}
void ReplicaSpace::activate(){Guard g(*this);require(writer&&shared->pid==getpid()&&!shared->damaged&&shared->head,"replica cannot activate");shared->blocked=false;}
bool ReplicaSpace::accept(const Change&e,int crash,bool sync_error,const std::function<void()>&before_sync) {
  diagnostic::mark("replica_accept",log_id,e.record.epoch,e.sequence);
  {Guard g(*this);
    require(writer&&shared->pid==getpid()&&!shared->damaged,"replica provider restricted by storage/conflict");
    if(e.sequence<=shared->head) {
      auto old=load(e.sequence);
      if(record_words_of(old)!=record_words_of(e)){shared->damaged=shared->blocked=true;++shared->generation;throw std::runtime_error("conflicting replica duplicate");}
      return false;
    }
    require(e.sequence==shared->head+1,"replica sequence gap");
    require(e.record.epoch>=shared->record.epoch,"replica epoch regression");
  }
  auto words=Words{protocol,log_id};auto rec=record_words_of(e);words.insert(words.end(),rec.begin(),rec.end());
  auto bytes=encode(words);require(bytes.size()==disk_bytes,"replica disk framing");
  auto at=static_cast<off_t>((e.sequence-1)*disk_bytes);
  try {
    diagnostic::mark("replica_write_begin",log_id,e.record.epoch,e.sequence);
    if(crash==1){io(journal,bytes.data(),bytes.size()/2,at,true);_exit(77);}
    io(journal,bytes.data(),bytes.size(),at,true);
    diagnostic::mark("replica_written",log_id,e.record.epoch,e.sequence);
    if(crash==2)_exit(77);
    if(before_sync)before_sync();
    if(sync_error){errno=EIO;check(false,"injected replica fdatasync");}
    diagnostic::mark("replica_sync_begin",log_id,e.record.epoch,e.sequence);
    sync_file(journal);
    diagnostic::mark("replica_sync_end",log_id,e.record.epoch,e.sequence);
    if(crash==3)_exit(77);
    diagnostic::mark("replica_publish_enter",log_id,e.record.epoch,e.sequence);
    {Guard g(*this);require(e.sequence==shared->head+1&&!shared->damaged,"replica concurrent provider mutation");
      diagnostic::mark("replica_publish_locked",log_id,e.record.epoch,e.sequence);install(e);
      diagnostic::mark("replica_published",log_id,e.record.epoch,e.sequence);}
    if(crash==4)_exit(77);
    return true;
  }catch(...){restrict(true);throw;}
}
}
