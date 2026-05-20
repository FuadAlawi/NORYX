import { useEffect, useMemo, useRef, useState } from 'react';
import grcExpertLogo from '../assets/grc-expert.png';

const API = 'http://127.0.0.1:8000';
const CHAT_TIMEOUT_MS = 95000;

const WELCOME = {
  en: 'Welcome to GRCXPERT Assistance.\n\nI can help explain GRC, cybersecurity, information security, compliance frameworks, controls, policies, governance, risks, and implementation guidance.',
  ar: 'مرحباً بك في GRCXPERT Assistance.\n\nيمكنني مساعدتك في شرح GRC والأمن السيبراني وأمن المعلومات وأطر الامتثال والضوابط والسياسات والحوكمة والمخاطر وكيفية تحقيق الامتثال.',
};

const PRIVATE_DATA_RESPONSE = {
  en: 'I do not have access to platform files or private assessment information. I only provide framework guidance and compliance education.',
  ar: 'لا أملك صلاحية الوصول إلى ملفات المنصة أو بيانات التقييم الخاصة. يمكنني فقط شرح الأطر ومفاهيم الامتثال.',
};

const OUT_OF_SCOPE_RESPONSE = {
  en: 'I can help with GRC, cybersecurity, information security, NCA ECC, ISO 27001, SAMA CSF, PDPL, compliance, governance, policies, policy violations, gaps, risk, controls, evidence examples, audit preparation, remediation, and how to implement cybersecurity requirements.',
  ar: 'يمكنني مساعدتك في GRC والأمن السيبراني وأمن المعلومات وNCA ECC وISO 27001 وSAMA CSF وPDPL والامتثال والحوكمة والسياسات والمخالفات والفجوات والمخاطر والضوابط والأدلة والاستعداد للتدقيق ومعالجة النواقص وكيفية تطبيق المتطلبات.',
};

const VIOLATION_AVOIDANCE_RESPONSE = {
  en: 'Companies can avoid compliance and policy violations by building a repeatable governance process, not only by writing policies.\n\n1. Define clear policies and map them to frameworks such as NCA ECC, ISO 27001, PDPL, or internal requirements.\n\n2. Assign owners for each control, policy, and remediation action so accountability is clear.\n\n3. Train employees regularly and require policy acknowledgment.\n\n4. Monitor key activities such as access changes, privileged accounts, data handling, backups, logging, and vendor access.\n\n5. Perform periodic gap assessments and internal audits to detect missing controls before an external audit.\n\n6. Keep evidence current, including approvals, screenshots, logs, reports, risk registers, and training records.\n\n7. Track exceptions with approval, expiry dates, compensating controls, and owner review.\n\n8. Remediate findings quickly, retest the control, and document closure.\n\nA strong approach is: policy -> control owner -> implementation -> evidence -> review -> remediation -> reassessment.',
  ar: 'يمكن للشركات تجنب مخالفات الامتثال والسياسات من خلال بناء عملية حوكمة مبنية على متابعة مستمرة، وليس فقط كتابة السياسات.\n\n1- تحديد سياسات واضحة وربطها بأطر مثل NCA ECC وISO 27001 وPDPL أو المتطلبات الداخلية.\n\n2- تعيين مالك لكل ضابط وسياسة وخطة معالجة حتى تكون المسؤولية واضحة.\n\n3- تدريب الموظفين بشكل دوري وتوثيق إقرارهم بفهم السياسات.\n\n4- مراقبة الأنشطة المهمة مثل تغييرات الصلاحيات، الحسابات عالية الامتياز، التعامل مع البيانات، النسخ الاحتياطي، السجلات، ووصول الموردين.\n\n5- تنفيذ تقييم فجوات وتدقيق داخلي بشكل دوري لاكتشاف النواقص قبل التدقيق الخارجي.\n\n6- تحديث الأدلة باستمرار مثل الموافقات، لقطات الشاشة، السجلات، التقارير، سجل المخاطر، وسجلات التدريب.\n\n7- إدارة الاستثناءات بموافقة رسمية، تاريخ انتهاء، ضوابط تعويضية، ومراجعة من المالك.\n\n8- معالجة الملاحظات بسرعة ثم اختبار الضابط وتوثيق الإغلاق.\n\nالمنهج الأفضل هو: سياسة -> مالك ضابط -> تطبيق -> دليل -> مراجعة -> معالجة -> إعادة تقييم.',
};

const VIOLATION_AVOIDANCE_PATTERNS = [
  /\bavoid\b[\s\S]*\bviolations?\b/i,
  /\bprevent\b[\s\S]*\bviolations?\b/i,
  /\breduce\b[\s\S]*\bviolations?\b/i,
  /\bviolations?\b[\s\S]*\bavoid\b/i,
  /\bviolations?\b[\s\S]*\bprevent\b/i,
  /\bviolations?\b[\s\S]*\breduce\b/i,
  /تجنب[\s\S]*مخالف/,
  /تفادي[\s\S]*مخالف/,
  /منع[\s\S]*مخالف/,
  /تقليل[\s\S]*مخالف/,
  /مخالف[\s\S]*تجنب/,
  /مخالف[\s\S]*تفادي/,
  /مخالف[\s\S]*منع/,
];

const READY_QUESTIONS = {
  en: [
    {
      question: 'What is ISO 27001?',
      answer: 'ISO 27001 is an international standard for building and operating an Information Security Management System (ISMS).\n\nIt helps organizations identify security risks, define policies, select controls, assign responsibilities, collect evidence, and improve security through audits and continual improvement.',
    },
    {
      question: 'What is NCA ECC?',
      answer: 'NCA ECC means Essential Cybersecurity Controls issued by Saudi Arabia’s National Cybersecurity Authority.\n\nIt defines baseline cybersecurity requirements for governance, asset management, access control, cyber defense, incident response, third-party security, and evidence-based compliance.',
    },
    {
      question: 'What is PDPL?',
      answer: 'PDPL is Saudi Arabia’s Personal Data Protection Law.\n\nIt regulates how personal data is collected, processed, stored, shared, retained, and protected. Organizations should define lawful processing, privacy notices, consent where required, retention rules, security controls, and data subject rights handling.',
    },
    {
      question: 'What does Compliant mean?',
      answer: 'Compliant means the requirement is fully satisfied.\n\nThe control is implemented, documented, operating as expected, and supported by current evidence such as policies, procedures, screenshots, logs, approvals, or reports.',
    },
    {
      question: 'What does Partially Compliant mean?',
      answer: 'Partially Compliant means some parts of the requirement are implemented, but important gaps still remain.\n\nCommon reasons include missing documentation, incomplete technical implementation, weak evidence, outdated records, or controls that are not consistently applied.',
    },
    {
      question: 'What does Non-Compliant mean?',
      answer: 'Non-Compliant means the requirement is not met, or the organization cannot prove it is met.\n\nThis may happen when a control is missing, a policy is not approved, evidence is unavailable, or the implemented process does not match the framework requirement.',
    },
    {
      question: 'How is risk calculated?',
      answer: 'Risk is commonly calculated as:\n\nImpact × Likelihood\n\nImpact measures how serious the damage could be, while likelihood measures how probable the event is. Organizations may also consider asset value, threats, vulnerabilities, and existing control effectiveness before choosing a treatment plan.',
    },
    {
      question: 'What evidence is commonly accepted?',
      answer: 'Common evidence includes:\n\nPolicies\nProcedures\nScreenshots\nSystem logs\nConfigurations\nAudit reports\nTraining records\nApprovals\nRisk registers\nIncident tickets\n\nGood evidence should be current, readable, relevant to the control, and clearly show who did what, when, and how the requirement is satisfied.',
    },
    {
      question: 'How can organizations comply with ISO 27001?',
      answer: 'Organizations can improve ISO 27001 compliance by defining the ISMS scope, performing risk assessments, selecting controls, creating policies, assigning owners, collecting evidence, and running internal audits.\n\nKey outputs usually include a risk register, Statement of Applicability, approved policies, control evidence, corrective actions, and management review records.',
    },
    {
      question: 'How can organizations comply with NCA ECC?',
      answer: 'Organizations can improve NCA ECC compliance by mapping each ECC control to responsible owners, implementing required governance and technical controls, documenting processes, and collecting cybersecurity evidence.\n\nPractical steps include gap assessment, remediation planning, policy approval, access reviews, logging, backup validation, incident response testing, and periodic reassessment.',
    },
    {
      question: 'How to comply with cybersecurity frameworks?',
      answer: 'To comply with cybersecurity frameworks, start by identifying which framework applies to the organization, such as NCA ECC, ISO 27001, PDPL, or another regulatory standard.\n\nA practical compliance approach includes:\n\n1. Define the scope, systems, departments, and data covered\n\n2. Perform a gap assessment against framework requirements\n\n3. Create or update policies and procedures\n\n4. Assign control owners and responsibilities\n\n5. Implement technical and governance controls\n\n6. Collect evidence such as logs, screenshots, approvals, reports, and training records\n\n7. Remediate failed or weak controls\n\n8. Run internal audits and management reviews\n\n9. Reassess regularly and keep evidence current\n\nCompliance is not a one-time task. It is an ongoing cycle of implementation, monitoring, documentation, audit, and continuous improvement.',
    },
    {
      question: 'How to remediate failed controls?',
      answer: '1. Identify the root cause\n\n2. Define a remediation owner and target date\n\n3. Implement the missing control or process\n\n4. Update related policies and procedures\n\n5. Collect clear evidence\n\n6. Test that the fix works\n\n7. Reassess compliance and close the finding',
    },
    {
      question: 'What policies are commonly required?',
      answer: 'Commonly required policies include:\n\nAccess control policy\nPassword policy\nBackup policy\nIncident response policy\nRisk management policy\nAsset management policy\nData protection policy\nAcceptable use policy\nSupplier security policy\n\nEach policy should be approved, communicated, reviewed periodically, and supported by implementation evidence.',
    },
  ],
  ar: [
    {
      question: 'ما هو ISO 27001؟',
      answer: 'ISO 27001 هو معيار دولي لبناء وتشغيل نظام إدارة أمن المعلومات ISMS.\n\nيساعد الجهة على تحديد المخاطر، وضع السياسات، اختيار الضوابط، توزيع المسؤوليات، جمع الأدلة، وتنفيذ التحسين المستمر من خلال التدقيق والمراجعات الدورية.',
    },
    {
      question: 'ما هو NCA ECC؟',
      answer: 'NCA ECC هو إطار الضوابط الأساسية للأمن السيبراني الصادر من الهيئة الوطنية للأمن السيبراني في السعودية.\n\nيحدد الحد الأدنى من متطلبات الأمن السيبراني مثل الحوكمة، إدارة الأصول، التحكم بالوصول، الحماية السيبرانية، الاستجابة للحوادث، وإثبات الامتثال بالأدلة.',
    },
    {
      question: 'ما هو PDPL؟',
      answer: 'PDPL هو نظام حماية البيانات الشخصية في السعودية.\n\nينظم جمع البيانات الشخصية ومعالجتها وتخزينها ومشاركتها وحمايتها. تحتاج الجهات إلى توضيح الغرض من المعالجة، حماية البيانات، إدارة الموافقات عند الحاجة، تحديد مدة الاحتفاظ، وتمكين حقوق أصحاب البيانات.',
    },
    {
      question: 'ماذا يعني Compliant؟',
      answer: 'Compliant يعني أن المتطلب محقق بالكامل.\n\nأي أن الضابط مطبق وموثق ويعمل بالشكل المطلوب، وتوجد أدلة حديثة تثبت ذلك مثل سياسة معتمدة، سجل، لقطة شاشة، تقرير، موافقة، أو إعدادات نظام.',
    },
    {
      question: 'ماذا يعني Partially Compliant؟',
      answer: 'Partially Compliant يعني وجود امتثال جزئي مع بقاء نواقص مهمة.\n\nقد يكون الضابط موجوداً لكن التوثيق غير مكتمل، أو الأدلة ضعيفة، أو التطبيق لا يغطي جميع الأنظمة، أو أن العملية لا تتم بشكل مستمر ومنتظم.',
    },
    {
      question: 'ماذا يعني Non-Compliant؟',
      answer: 'Non-Compliant يعني أن المتطلب غير محقق أو لا توجد أدلة كافية لإثبات تحقيقه.\n\nقد يكون السبب عدم وجود ضابط، عدم اعتماد السياسة، غياب السجلات، أو أن التطبيق الحالي لا يطابق متطلبات الإطار.',
    },
    {
      question: 'كيف يتم حساب المخاطر؟',
      answer: 'يتم حساب المخاطر غالباً بهذه المعادلة:\n\nالمخاطر = التأثير × الاحتمالية\n\nالتأثير يوضح حجم الضرر المحتمل، والاحتمالية توضح فرصة حدوثه. ويمكن أيضاً مراعاة قيمة الأصل، التهديدات، نقاط الضعف، وفعالية الضوابط الحالية قبل اختيار خطة المعالجة.',
    },
    {
      question: 'ما الأدلة المقبولة عادة؟',
      answer: 'الأدلة المقبولة عادة تشمل:\n\nالسياسات\nالإجراءات\nالسجلات\nالتقارير\nلقطات الشاشة\nإعدادات الأنظمة\nسجلات التدريب\nالموافقات\nسجل المخاطر\nتذاكر الحوادث\n\nالدليل الجيد يجب أن يكون حديثاً وواضحاً ومرتبطاً بالضابط ويثبت من قام بالإجراء ومتى وكيف تم تحقيق المتطلب.',
    },
    {
      question: 'كيف يمكن تحقيق الامتثال؟',
      answer: 'يمكن تحقيق الامتثال من خلال فهم المتطلبات، تنفيذ الضوابط، اعتماد السياسات، توزيع المسؤوليات، وتوثيق الأدلة.\n\nينصح أيضاً بتنفيذ تقييم فجوات، وضع خطة معالجة، تدريب الموظفين، مراجعة الأدلة بشكل دوري، وإعادة التقييم للتأكد من أن الضوابط تعمل فعلياً.',
    },
    {
      question: 'كيف يمكن الامتثال لأطر الأمن السيبراني؟',
      answer: 'للامتثال لأطر الأمن السيبراني، ابدأ بتحديد الإطار المناسب للجهة مثل NCA ECC أو ISO 27001 أو PDPL أو أي متطلبات تنظيمية أخرى.\n\nالمنهج العملي يشمل:\n\n1- تحديد النطاق: الأنظمة، الإدارات، البيانات، والخدمات المشمولة\n\n2- تنفيذ تقييم فجوات مقابل متطلبات الإطار\n\n3- إنشاء أو تحديث السياسات والإجراءات\n\n4- تحديد مالكي الضوابط والمسؤوليات\n\n5- تطبيق الضوابط التقنية والحوكمية\n\n6- جمع الأدلة مثل السجلات، لقطات الشاشة، الموافقات، التقارير، وسجلات التدريب\n\n7- معالجة الضوابط الضعيفة أو غير المحققة\n\n8- تنفيذ تدقيق داخلي ومراجعة إدارية\n\n9- إعادة التقييم بشكل دوري وتحديث الأدلة\n\nالامتثال ليس مهمة لمرة واحدة، بل دورة مستمرة من التطبيق، المراقبة، التوثيق، التدقيق، والتحسين المستمر.',
    },
    {
      question: 'كيف تتم معالجة الضوابط الفاشلة؟',
      answer: '1- معرفة السبب الجذري للفشل\n\n2- تحديد مالك للمعالجة وتاريخ مستهدف\n\n3- تطبيق الضابط أو الإجراء الناقص\n\n4- تحديث السياسات والإجراءات ذات العلاقة\n\n5- جمع أدلة واضحة وحديثة\n\n6- اختبار فعالية المعالجة\n\n7- إعادة التقييم وإغلاق الملاحظة',
    },
  ],
};

const PRIVATE_PATTERNS = [
  /\bmy uploaded\b/i,
  /\bour uploaded\b/i,
  /\buploaded evidence\b/i,
  /\bplatform files?\b/i,
  /\bplatform data\b/i,
  /\bprivate assessment\b/i,
  /\bassessment result/i,
  /\bcompliance score\b/i,
  /\bdashboard data\b/i,
  /\buser files?\b/i,
  /\bemployee tasks?\b/i,
  /\bprivate company data\b/i,
  /\bcompany files?\b/i,
  /\bdatabase\b/i,
  /\bshow me my\b/i,
  /\bread my\b/i,
  /\bopen my\b/i,
  /\bmy report\b/i,
  /\bour report\b/i,
  /ملفات المنصة/,
  /بيانات المنصة/,
  /تقييمي/,
  /نتائج التقييم/,
  /درجة الامتثال/,
  /لوحة المعلومات/,
  /مهام الموظفين/,
  /قاعدة البيانات/,
  /ملفاتي/,
  /الأدلة المرفوعة/,
];

const ALLOWED_PATTERNS = [
  /\bgrc\b/i,
  /\bgovernance risk compliance\b/i,
  /\binformation security\b/i,
  /\binformation secuirty\b/i,
  /\binfosec\b/i,
  /\bisms\b/i,
  /\bcia triad\b/i,
  /\bnca\b/i,
  /\becc\b/i,
  /\biso\b/i,
  /\bsama\b/i,
  /\bcsf\b/i,
  /\b27001\b/i,
  /\bpdpl\b/i,
  /\bcompliance\b/i,
  /\bcompliant\b/i,
  /\bcomply\b/i,
  /\bgovernance\b/i,
  /\bpolicy\b/i,
  /\bpolicies\b/i,
  /\bviolation\b/i,
  /\bviolations\b/i,
  /\bgap\b/i,
  /\bgaps\b/i,
  /\bfinding\b/i,
  /\bfindings\b/i,
  /\bnonconformity\b/i,
  /\bnon-conformity\b/i,
  /\bnonconformities\b/i,
  /\bnon-conformities\b/i,
  /\bdeficiency\b/i,
  /\bdeficiencies\b/i,
  /\bexception\b/i,
  /\bexceptions\b/i,
  /\brisk\b/i,
  /\bthreat\b/i,
  /\bthreats\b/i,
  /\battack\b/i,
  /\battacks\b/i,
  /\bmalware\b/i,
  /\bphishing\b/i,
  /\bransomware\b/i,
  /\bcontrol\b/i,
  /\bcontrols\b/i,
  /\bevidence\b/i,
  /\baudit\b/i,
  /\bremediation\b/i,
  /\bremediate\b/i,
  /\bcybersecurity\b/i,
  /\bcyber security\b/i,
  /\bcyberseciety\b/i,
  /\bcybersecuirty\b/i,
  /\bsecurity\b/i,
  /\bsecuirty\b/i,
  /\bframework\b/i,
  /\brequirement\b/i,
  /\bimplement\b/i,
  /\baccess\b/i,
  /\bidentity\b/i,
  /\biam\b/i,
  /\bauthentication\b/i,
  /\bauthorization\b/i,
  /\bmfa\b/i,
  /\bpassword\b/i,
  /\bfirewall\b/i,
  /\bnetwork security\b/i,
  /\bendpoint\b/i,
  /\bcloud security\b/i,
  /\bdata protection\b/i,
  /\bprivacy\b/i,
  /\bsoc\b/i,
  /\bsiem\b/i,
  /\bawareness\b/i,
  /\bincident\b/i,
  /\bencryption\b/i,
  /\bvulnerability\b/i,
  /\bbackup\b/i,
  /\btraining\b/i,
  /امتثال/,
  /حوكمة المخاطر والامتثال/,
  /أمن المعلومات/,
  /امن المعلومات/,
  /سرية/,
  /سلامة/,
  /توافر/,
  /متوافق/,
  /السيبراني/,
  /الأمن/,
  /امن/,
  /ضابط/,
  /ضوابط/,
  /سياس/,
  /مخالف/,
  /فجوة/,
  /فجوات/,
  /ثغرة/,
  /ثغرات/,
  /نقص/,
  /نواقص/,
  /ملاحظة/,
  /ملاحظات/,
  /مخاطر/,
  /المخاطر/,
  /تهديد/,
  /تهديدات/,
  /هجوم/,
  /هجمات/,
  /اختراق/,
  /تصيد/,
  /برمجيات خبيثة/,
  /فدية/,
  /حوكمة/,
  /الحوكمة/,
  /أدلة/,
  /دليل/,
  /تدقيق/,
  /معالجة/,
  /تطبيق/,
  /متطلبات/,
  /حماية البيانات/,
  /خصوصية/,
  /صلاحيات/,
  /مصادقة/,
  /هوية/,
  /كلمة المرور/,
  /جدار حماية/,
  /ايزو/,
  /آيزو/,
];

function createMessage(role, text) {
  const id = `${role}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return { id, role, text };
}

function isPrivateDataRequest(text) {
  return PRIVATE_PATTERNS.some(pattern => pattern.test(text));
}

function isAllowedTopic(text) {
  return ALLOWED_PATTERNS.some(pattern => pattern.test(text));
}

function getPredefinedCustomAnswer(text, language) {
  if (VIOLATION_AVOIDANCE_PATTERNS.some(pattern => pattern.test(text))) {
    return VIOLATION_AVOIDANCE_RESPONSE[language];
  }
  return '';
}

export default function GRCXPERTAssistance() {
  const [open, setOpen] = useState(false);
  const [language, setLanguage] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef(null);

  const isArabic = language === 'ar';
  const readyQuestions = useMemo(() => READY_QUESTIONS[language] || [], [language]);

  useEffect(() => {
    if (!open) return;
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, loading, open]);

  const selectLanguage = (nextLanguage) => {
    setLanguage(nextLanguage);
    setMessages([createMessage('assistant', WELCOME[nextLanguage])]);
    setInput('');
    setLoading(false);
  };

  const resetLanguage = () => {
    setLanguage(null);
    setMessages([]);
    setInput('');
    setLoading(false);
  };

  const appendExchange = (question, answer) => {
    setMessages(current => [
      ...current,
      createMessage('user', question),
      createMessage('assistant', answer),
    ]);
  };

  const handleReadyQuestion = (item) => {
    appendExchange(item.question, item.answer);
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    const question = input.trim();
    if (!question || !language || loading) return;

    setInput('');
    setMessages(current => [...current, createMessage('user', question)]);

    if (isPrivateDataRequest(question)) {
      setMessages(current => [...current, createMessage('assistant', PRIVATE_DATA_RESPONSE[language])]);
      return;
    }

    if (!isAllowedTopic(question)) {
      setMessages(current => [...current, createMessage('assistant', OUT_OF_SCOPE_RESPONSE[language])]);
      return;
    }

    const predefinedAnswer = getPredefinedCustomAnswer(question, language);
    if (predefinedAnswer) {
      setMessages(current => [...current, createMessage('assistant', predefinedAnswer)]);
      return;
    }

    setLoading(true);
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);
    try {
      const response = await fetch(`${API}/grcxpert-assistance/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: question, language }),
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || 'Unable to reach GRCXPERT Assistance.');
      }
      setMessages(current => [
        ...current,
        createMessage('assistant', data.answer || OUT_OF_SCOPE_RESPONSE[language]),
      ]);
    } catch (error) {
      const timedOut = error?.name === 'AbortError';
      const fallback = language === 'ar'
        ? timedOut
          ? 'استغرقت الإجابة وقتاً أطول من المتوقع. يرجى المحاولة مرة أخرى بسؤال أقصر، أو التأكد من أن الخدمة المحلية تعمل بشكل طبيعي.'
          : 'تعذر الوصول إلى مساعد GRCEXPERT المحلي حالياً. يرجى التأكد من تشغيل الخدمة المحلية.'
        : timedOut
          ? 'The answer took longer than expected. Please try a shorter question or make sure the local service is running normally.'
          : 'GRCEXPERT Assistance could not reach the local assistant right now. Please make sure the local service is running.';
      setMessages(current => [...current, createMessage('assistant', fallback)]);
    } finally {
      window.clearTimeout(timeoutId);
      setLoading(false);
    }
  };

  return (
    <div className={`grcxpert-assistance ${open ? 'is-open' : ''}`}>
      {open && (
        <section className="grcxpert-panel" aria-label="GRCXPERT Assistance" dir={isArabic ? 'rtl' : 'ltr'}>
          <header className="grcxpert-panel-header">
            <div className="grcxpert-title-block">
              <div className="grcxpert-mark" aria-hidden="true">
                <img src={grcExpertLogo} alt="" />
              </div>
              <div>
                <div className="grcxpert-title">GRCEXPERT ASSISTANCE</div>
              </div>
            </div>
            <div className="grcxpert-header-actions">
              {language && (
                <button
                  type="button"
                  className="grcxpert-language-reset"
                  onClick={resetLanguage}
                  aria-label={isArabic ? 'اللغة' : 'Language'}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <circle cx="12" cy="12" r="8" />
                    <path d="M4 12h16" />
                    <path d="M12 4c2.2 2.1 3.3 4.7 3.3 8s-1.1 5.9-3.3 8" />
                    <path d="M12 4c-2.2 2.1-3.3 4.7-3.3 8s1.1 5.9 3.3 8" />
                  </svg>
                </button>
              )}
              <button
                type="button"
                className="grcxpert-icon-button"
                onClick={() => setOpen(false)}
                aria-label="Close GRCXPERT Assistance"
                title="Close"
              >
                ×
              </button>
            </div>
          </header>

          {!language ? (
            <div className="grcxpert-language-screen">
              <div className="grcxpert-language-copy">
                <div className="grcxpert-language-title">Choose preferred language</div>
                <div className="grcxpert-language-title grcxpert-language-title-ar" dir="rtl">اختر اللغة المفضلة</div>
              </div>
              <div className="grcxpert-language-actions">
                <button type="button" className="grcxpert-language-button" onClick={() => selectLanguage('ar')}>
                  العربية
                </button>
                <button type="button" className="grcxpert-language-button" onClick={() => selectLanguage('en')}>
                  English
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="grcxpert-messages" ref={scrollRef}>
                {messages.map(message => (
                  <div key={message.id} className={`grcxpert-message-row ${message.role}`}>
                    <div className="grcxpert-message-bubble" dir="auto">
                      {message.text}
                    </div>
                  </div>
                ))}
                {loading && (
                  <div className="grcxpert-message-row assistant">
                    <div className="grcxpert-message-bubble grcxpert-loading" aria-live="polite">
                      <span />
                      <span />
                      <span />
                    </div>
                  </div>
                )}
              </div>

              <div className="grcxpert-ready-section">
                <div className="grcxpert-ready-grid">
                  {readyQuestions.map(item => (
                    <button
                      key={item.question}
                      type="button"
                      className="grcxpert-ready-question"
                      onClick={() => handleReadyQuestion(item)}
                      disabled={loading}
                    >
                      {item.question}
                    </button>
                  ))}
                </div>
              </div>

              <form className="grcxpert-input-row" onSubmit={handleSubmit}>
                <input
                  value={input}
                  onChange={event => setInput(event.target.value)}
                  placeholder=""
                  aria-label={isArabic ? 'سؤال GRCEXPERT Assistance' : 'GRCEXPERT Assistance question'}
                  disabled={loading}
                  dir="auto"
                />
                <button type="submit" className="grcxpert-send-button" disabled={!input.trim() || loading}>
                  {isArabic ? 'إرسال' : 'Send'}
                </button>
              </form>
            </>
          )}
        </section>
      )}

      <button
        type="button"
        className="grcxpert-launcher"
        onClick={() => setOpen(current => !current)}
        aria-expanded={open}
        aria-label="GRCXPERT Assistance"
      >
        <span className="grcxpert-launcher-icon" aria-hidden="true">
          <img src={grcExpertLogo} alt="" />
        </span>
      </button>
    </div>
  );
}
