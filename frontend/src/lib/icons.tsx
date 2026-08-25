import type { ComponentType, SVGProps } from "react";
import {
  AdjustmentsHorizontalIcon, ArchiveBoxIcon, ArrowDownIcon, ArrowDownOnSquareIcon,
  ArrowDownRightIcon, ArrowDownTrayIcon, ArrowLeftIcon, ArrowPathIcon,
  ArrowPathRoundedSquareIcon, ArrowRightEndOnRectangleIcon, ArrowRightIcon, ArrowRightStartOnRectangleIcon,
  ArrowTopRightOnSquareIcon, ArrowTrendingDownIcon, ArrowTrendingUpIcon, ArrowTurnDownRightIcon,
  ArrowUpRightIcon, ArrowUpTrayIcon, ArrowUturnLeftIcon, ArrowUturnRightIcon,
  ArrowsPointingOutIcon, ArrowsRightLeftIcon, ArrowsUpDownIcon, AtSymbolIcon,
  BackwardIcon, Bars3Icon, BeakerIcon, BellAlertIcon,
  BellIcon, BellSlashIcon, BoltIcon, BookOpenIcon,
  BookmarkIcon as HeroBookmarkIcon, BuildingOffice2Icon, BuildingOfficeIcon, CalculatorIcon,
  CalendarDateRangeIcon, CalendarDaysIcon, CameraIcon, ChartBarIcon,
  ChatBubbleLeftIcon, ChatBubbleLeftRightIcon, CheckBadgeIcon, CheckCircleIcon,
  CheckIcon, ChevronDownIcon as HeroChevronDownIcon, ChevronLeftIcon as HeroChevronLeftIcon, ChevronRightIcon as HeroChevronRightIcon,
  ChevronUpIcon as HeroChevronUpIcon, CircleStackIcon, ClipboardDocumentListIcon, ClockIcon,
  CloudArrowDownIcon, CodeBracketIcon, Cog6ToothIcon, Cog8ToothIcon,
  CommandLineIcon, ComputerDesktopIcon, CpuChipIcon, CreditCardIcon,
  CurrencyDollarIcon, CurrencyRupeeIcon, DocumentArrowDownIcon, DocumentChartBarIcon,
  DocumentCheckIcon, DocumentDuplicateIcon, DocumentMinusIcon, DocumentTextIcon,
  EllipsisHorizontalIcon, EnvelopeIcon, ExclamationCircleIcon, ExclamationTriangleIcon,
  EyeIcon, EyeSlashIcon, FireIcon, FlagIcon,
  ForwardIcon, FunnelIcon, GiftIcon, GiftTopIcon,
  GlobeAltIcon, GlobeAsiaAustraliaIcon, HandThumbDownIcon, HandThumbUpIcon,
  HashtagIcon, HeartIcon, HomeIcon, InboxIcon,
  InformationCircleIcon, KeyIcon, LanguageIcon, LinkIcon,
  ListBulletIcon, LockClosedIcon, MagnifyingGlassIcon, MapIcon,
  MapPinIcon, MegaphoneIcon, MicrophoneIcon, MinusIcon,
  MoonIcon, NoSymbolIcon, NumberedListIcon, PaperAirplaneIcon,
  PauseCircleIcon, PauseIcon, PencilIcon, PencilSquareIcon,
  PhoneArrowDownLeftIcon, PhoneArrowUpRightIcon, PhoneIcon, PhoneXMarkIcon,
  PhotoIcon, PlayCircleIcon, PlayIcon, PlusIcon,
  QrCodeIcon, QuestionMarkCircleIcon, QueueListIcon, RectangleGroupIcon,
  RocketLaunchIcon, ServerIcon, ShieldCheckIcon, ShieldExclamationIcon,
  SignalSlashIcon, SparklesIcon, SpeakerWaveIcon, SpeakerXMarkIcon,
  Square3Stack3DIcon, Squares2X2Icon, StarIcon, StopIcon,
  SunIcon, SwatchIcon, TableCellsIcon, TagIcon,
  TrashIcon, TrophyIcon, TruckIcon, UserCircleIcon,
  UserGroupIcon, UserIcon, UserMinusIcon, UserPlusIcon,
  UsersIcon, ViewfinderCircleIcon, WalletIcon, WifiIcon,
  XCircleIcon, XMarkIcon,
} from "@heroicons/react/24/outline";

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "ref"> {
  size?: number | string;
}

function withSize(Icon: ComponentType<Omit<SVGProps<SVGSVGElement>, "ref">>) {
  return function SizedIcon({ size, ...props }: IconProps) {
    return <Icon width={size} height={size} {...props} />;
  };
}

export const AlertCircle = withSize(ExclamationCircleIcon);
export const AlertTriangle = withSize(ExclamationTriangleIcon);
export const Archive = withSize(ArchiveBoxIcon);
export const ArrowDown = withSize(ArrowDownIcon);
export const ArrowDownRight = withSize(ArrowDownRightIcon);
export const ArrowLeft = withSize(ArrowLeftIcon);
export const ArrowRight = withSize(ArrowRightIcon);
export const ArrowUpDown = withSize(ArrowsUpDownIcon);
export const ArrowUpRight = withSize(ArrowUpRightIcon);
export const AtSign = withSize(AtSymbolIcon);
export const Award = withSize(TrophyIcon);
export const BadgeCheck = withSize(CheckBadgeIcon);
export const Ban = withSize(NoSymbolIcon);
export const BarChart2 = withSize(ChartBarIcon);
export const BarChart3 = withSize(ChartBarIcon);
export const Bell = withSize(BellIcon);
export const BellOff = withSize(BellSlashIcon);
export const BellRing = withSize(BellAlertIcon);
export const BookOpen = withSize(BookOpenIcon);
export const BookmarkIcon = withSize(HeroBookmarkIcon);
export const Bot = withSize(CpuChipIcon);
export const Building = withSize(BuildingOfficeIcon);
export const Building2 = withSize(BuildingOffice2Icon);
export const Calculator = withSize(CalculatorIcon);
export const Calendar = withSize(CalendarDaysIcon);
export const CalendarCheck = withSize(CalendarDateRangeIcon);
export const CalendarCheck2 = withSize(CalendarDateRangeIcon);
export const CalendarClock = withSize(CalendarDateRangeIcon);
export const CalendarX = withSize(CalendarDaysIcon);
export const Camera = withSize(CameraIcon);
export const Check = withSize(CheckIcon);
export const CheckCheck = withSize(CheckBadgeIcon);
export const CheckCircle = withSize(CheckCircleIcon);
export const CheckCircle2 = withSize(CheckCircleIcon);
export const CheckSquare = withSize(CheckCircleIcon);
export const ChevronDown = withSize(HeroChevronDownIcon);
export const ChevronDownIcon = withSize(HeroChevronDownIcon);
export const ChevronLeft = withSize(HeroChevronLeftIcon);
export const ChevronLeftIcon = withSize(HeroChevronLeftIcon);
export const ChevronRight = withSize(HeroChevronRightIcon);
export const ChevronRightIcon = withSize(HeroChevronRightIcon);
export const ChevronUp = withSize(HeroChevronUpIcon);
export const ChevronUpIcon = withSize(HeroChevronUpIcon);
export const ClipboardList = withSize(ClipboardDocumentListIcon);
export const Clock = withSize(ClockIcon);
export const CloudDownload = withSize(CloudArrowDownIcon);
export const Code2 = withSize(CodeBracketIcon);
export const Copy = withSize(DocumentDuplicateIcon);
export const CornerDownRight = withSize(ArrowTurnDownRightIcon);
export const CreditCard = withSize(CreditCardIcon);
export const Database = withSize(CircleStackIcon);
export const Delete = withSize(TrashIcon);
export const DollarSign = withSize(CurrencyDollarIcon);
export const Download = withSize(ArrowDownTrayIcon);
export const Edit2 = withSize(PencilSquareIcon);
export const ExternalLink = withSize(ArrowTopRightOnSquareIcon);
export const Eye = withSize(EyeIcon);
export const EyeOff = withSize(EyeSlashIcon);
export const FileCheck2 = withSize(DocumentCheckIcon);
export const FileDown = withSize(DocumentArrowDownIcon);
export const FileSpreadsheet = withSize(DocumentChartBarIcon);
export const FileText = withSize(DocumentTextIcon);
export const FileWarning = withSize(DocumentMinusIcon);
export const Filter = withSize(FunnelIcon);
export const Flag = withSize(FlagIcon);
export const Flame = withSize(FireIcon);
export const FlaskConical = withSize(BeakerIcon);
export const Gift = withSize(GiftIcon);
export const Globe = withSize(GlobeAltIcon);
export const Globe2 = withSize(GlobeAsiaAustraliaIcon);
export const GripVertical = withSize(Bars3Icon);
export const Hash = withSize(HashtagIcon);
export const Heart = withSize(HeartIcon);
export const HeartHandshake = withSize(HeartIcon);
export const HelpCircle = withSize(QuestionMarkCircleIcon);
export const History = withSize(ClockIcon);
export const Home = withSize(HomeIcon);
export const Hotel = withSize(BuildingOffice2Icon);
export const Image = withSize(PhotoIcon);
export const ImageIcon = withSize(PhotoIcon);
export const Inbox = withSize(InboxIcon);
export const Instagram = withSize(ChatBubbleLeftIcon);
export const IndianRupee = withSize(CurrencyRupeeIcon);
export const Info = withSize(InformationCircleIcon);
export const Key = withSize(KeyIcon);
export const KeyRound = withSize(KeyIcon);
export const Keyboard = withSize(CommandLineIcon);
export const Languages = withSize(LanguageIcon);
export const Layers = withSize(Square3Stack3DIcon);
export const LayoutDashboard = withSize(Squares2X2Icon);
export const LayoutGrid = withSize(Squares2X2Icon);
export const LayoutTemplate = withSize(RectangleGroupIcon);
export const Link2 = withSize(LinkIcon);
export const List = withSize(ListBulletIcon);
export const ListChecks = withSize(QueueListIcon);
export const ListOrdered = withSize(NumberedListIcon);
export const Loader = withSize(ArrowPathIcon);
export const Loader2 = withSize(ArrowPathIcon);
export const Lock = withSize(LockClosedIcon);
export const LogIn = withSize(ArrowRightEndOnRectangleIcon);
export const LogOut = withSize(ArrowRightStartOnRectangleIcon);
export const Mail = withSize(EnvelopeIcon);
export const Map = withSize(MapIcon);
export const MapPin = withSize(MapPinIcon);
export const Megaphone = withSize(MegaphoneIcon);
export const Menu = withSize(Bars3Icon);
export const MessageCircle = withSize(ChatBubbleLeftIcon);
export const MessageSquare = withSize(ChatBubbleLeftRightIcon);
export const MessagesSquare = withSize(ChatBubbleLeftRightIcon);
export const Mic2 = withSize(MicrophoneIcon);
export const Minus = withSize(MinusIcon);
export const Monitor = withSize(ComputerDesktopIcon);
export const Moon = withSize(MoonIcon);
export const MoreHorizontal = withSize(EllipsisHorizontalIcon);
export const Move = withSize(ArrowsPointingOutIcon);
export const Palette = withSize(SwatchIcon);
export const PartyPopper = withSize(GiftTopIcon);
export const Pause = withSize(PauseIcon);
export const PauseCircle = withSize(PauseCircleIcon);
export const Pencil = withSize(PencilIcon);
export const Phone = withSize(PhoneIcon);
export const PhoneCall = withSize(PhoneArrowUpRightIcon);
export const PhoneIncoming = withSize(PhoneArrowDownLeftIcon);
export const PhoneMissed = withSize(PhoneXMarkIcon);
export const PhoneOutgoing = withSize(PhoneArrowUpRightIcon);
export const Plane = withSize(PaperAirplaneIcon);
export const Play = withSize(PlayIcon);
export const PlayCircle = withSize(PlayCircleIcon);
export const Plus = withSize(PlusIcon);
export const QrCode = withSize(QrCodeIcon);
export const RefreshCw = withSize(ArrowPathIcon);
export const RepeatIcon = withSize(ArrowPathRoundedSquareIcon);
export const Reply = withSize(ArrowUturnLeftIcon);
export const Rocket = withSize(RocketLaunchIcon);
export const RotateCcw = withSize(ArrowUturnLeftIcon);
export const RotateCw = withSize(ArrowUturnRightIcon);
export const Save = withSize(ArrowDownOnSquareIcon);
export const Search = withSize(MagnifyingGlassIcon);
export const Send = withSize(PaperAirplaneIcon);
export const Server = withSize(ServerIcon);
export const Settings = withSize(Cog6ToothIcon);
export const Settings2 = withSize(Cog8ToothIcon);
export const Shield = withSize(ShieldCheckIcon);
export const ShieldAlert = withSize(ShieldExclamationIcon);
export const ShieldCheck = withSize(ShieldCheckIcon);
export const Shuffle = withSize(ArrowsRightLeftIcon);
export const SkipBack = withSize(BackwardIcon);
export const SkipForward = withSize(ForwardIcon);
export const Sliders = withSize(AdjustmentsHorizontalIcon);
export const SlidersHorizontal = withSize(AdjustmentsHorizontalIcon);
export const Sparkles = withSize(SparklesIcon);
export const Square = withSize(StopIcon);
export const Star = withSize(StarIcon);
export const StickyNote = withSize(DocumentTextIcon);
export const Sun = withSize(SunIcon);
export const Table2 = withSize(TableCellsIcon);
export const Tag = withSize(TagIcon);
export const Tags = withSize(TagIcon);
export const Target = withSize(ViewfinderCircleIcon);
export const ThumbsDown = withSize(HandThumbDownIcon);
export const ThumbsUp = withSize(HandThumbUpIcon);
export const Timer = withSize(ClockIcon);
export const Trash2 = withSize(TrashIcon);
export const TrendingDown = withSize(ArrowTrendingDownIcon);
export const TrendingUp = withSize(ArrowTrendingUpIcon);
export const Truck = withSize(TruckIcon);
export const Upload = withSize(ArrowUpTrayIcon);
export const User = withSize(UserIcon);
export const UserCircle = withSize(UserCircleIcon);
export const UserPlus = withSize(UserPlusIcon);
export const UserX = withSize(UserMinusIcon);
export const Users = withSize(UsersIcon);
export const UsersRound = withSize(UserGroupIcon);
export const Volume2 = withSize(SpeakerWaveIcon);
export const VolumeX = withSize(SpeakerXMarkIcon);
export const Wallet = withSize(WalletIcon);
export const Wand2 = withSize(SparklesIcon);
export const Wifi = withSize(WifiIcon);
export const WifiOff = withSize(SignalSlashIcon);
export const Workflow = withSize(RectangleGroupIcon);
export const X = withSize(XMarkIcon);
export const XCircle = withSize(XCircleIcon);
export const Zap = withSize(BoltIcon);
